from uuid import uuid4

from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase
from django.urls import reverse

from store.models import DocumentCorrection, StockBalance, WebOrder
from store.services.documents import (
    cancel_draft,
    confirm_document,
    correct_document,
    create_document,
)
from store.services.orders import accept_order, cancel_order
from store.tests import test_shop as shop_tests
from store.tests.test_business import fixture


class CustomerCorrectionStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = fixture()
        shop_tests.stock(cls.admin, cls.v)

    add = shop_tests.ShopTests.add
    prepare = shop_tests.ShopTests.prepare
    place = shop_tests.ShopTests.place

    def test_customer_order_reflects_full_correction_of_a_completed_counter_sale(self):
        order, _ = self.place()
        self.assertEqual(order.lifecycle_status, "PENDING")
        order = accept_order(self.sales, order.pk, order.version)
        self.assertEqual(order.lifecycle_status, "ACCEPTED")
        sale = order.sale
        confirm_document(
            self.sales,
            "sale",
            sale.pk,
            sale.version,
            uuid4(),
            {
                "method": "CASH",
                "cash_received": str(sale.total_amount),
            },
        )
        self.assertContains(
            self.client.get(reverse("shop_order", args=[order.pk])), "Đã hoàn tất tại cửa hàng"
        )
        staff = Client()
        staff.force_login(self.sales)
        self.assertNotContains(staff.get(reverse("web_orders"), {"status": "ACCEPTED"}), order.code)
        self.assertContains(staff.get(reverse("web_orders"), {"status": "COMPLETED"}), order.code)
        correct_document(
            self.admin,
            "sale",
            sale.pk,
            uuid4(),
            reason="Sai giao dịch",
            evidence="Chứng từ kiểm tra",
            goods_ack=True,
            financial_ack=True,
        )
        order = WebOrder.objects.select_related("sale").get(pk=order.pk)
        self.assertEqual(order.display_status, "Đơn bán đã được sửa sai toàn bộ")
        response = self.client.get(reverse("shop_order", args=[order.pk]))
        self.assertContains(response, "Giao dịch gốc đã có chứng từ bù trừ")
        self.assertNotContains(response, "Đơn bán đã được hoàn tất tại quầy")
        self.assertContains(
            self.client.get(reverse("shop_orders")), "Đơn bán đã được sửa sai toàn bộ"
        )
        self.assertNotContains(
            staff.get(reverse("web_orders"), {"status": "COMPLETED"}), order.code
        )
        self.assertContains(staff.get(reverse("web_orders"), {"status": "CORRECTED"}), order.code)
        self.assertEqual(StockBalance.objects.get(variant=self.v).quantity, 8)

    def test_lifecycle_labels_for_a_list_are_read_in_one_database_query(self):
        self.place()
        with self.assertNumQueries(1):
            orders = list(WebOrder.objects.with_lifecycle())
            self.assertEqual([o.display_status for o in orders], ["Chờ xác nhận"])

    def test_cancelled_linked_sale_is_projected_by_database_for_both_interfaces(self):
        order, _ = self.place()
        order = accept_order(self.sales, order.pk, order.version)
        cancel_draft(self.sales, "sale", order.sale_id, order.sale.version, "Khách không nhận hàng")
        self.assertEqual(order.lifecycle_status, "SALE_CANCELLED")
        self.assertContains(
            self.client.get(reverse("shop_order", args=[order.pk])), "Cửa hàng đã hủy đơn bán"
        )
        staff = Client()
        staff.force_login(self.sales)
        self.assertContains(
            staff.get(reverse("web_orders"), {"status": "SALE_CANCELLED"}), order.code
        )
        self.assertNotContains(staff.get(reverse("web_orders"), {"status": "ACCEPTED"}), order.code)


class SQLLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = fixture()
        shop_tests.stock(cls.admin, cls.v)

    add = shop_tests.ShopTests.add
    prepare = shop_tests.ShopTests.prepare
    place = shop_tests.ShopTests.place

    def reject(self, sql, params, constraint):
        with self.assertRaises(IntegrityError) as error, transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self.assertEqual(error.exception.__cause__.diag.constraint_name, constraint)

    def test_SQL28_cancelled_web_request_cannot_be_reopened_by_SQL(self):
        order, _ = self.place()
        cancel_order(order.pk, order.version, owner=order.owner_hash)
        self.reject(
            "UPDATE store_weborder SET status='PENDING',handled_at=NULL,reason='',cancel_origin='',version=version+1 WHERE id=%s",
            [order.pk],
            "nep_web_transition_valid",
        )
        self.assertEqual(WebOrder.objects.get(pk=order.pk).lifecycle_status, "CANCELLED")

    def test_SQL29_accepted_request_cannot_be_linked_to_another_sale(self):
        order, _ = self.place()
        order = accept_order(self.sales, order.pk, order.version)
        other = create_document(self.sales, "sale", {})
        self.reject(
            "UPDATE store_weborder SET sale_id=%s,version=version+1 WHERE id=%s",
            [other.pk, order.pk],
            "nep_web_transition_valid",
        )

    def test_SQL30_cancelled_documents_cannot_be_reopened(self):
        sale = create_document(self.admin, "sale", {})
        docs = [
            sale,
            create_document(self.admin, "receipt", {"supplier": self.supplier}),
            create_document(self.admin, "adjustment", {"kind": "COUNT", "reason": "Kiểm thử"}),
            DocumentCorrection.objects.create(
                code="BS-TEST",
                created_by=self.admin,
                original_sale=sale,
                reason="Kiểm thử",
                evidence="Kiểm thử",
            ),
        ]
        for doc in docs:
            with self.subTest(table=doc._meta.db_table):
                kind = {
                    "SaleOrder": "sale",
                    "GoodsReceipt": "receipt",
                    "StockAdjustment": "adjustment",
                    "DocumentCorrection": "correction",
                }[type(doc).__name__]
                cancel_draft(self.admin, kind, doc.pk, doc.version, "Hủy kiểm thử")
                self.reject(
                    f"UPDATE {connection.ops.quote_name(doc._meta.db_table)} SET status='DRAFT' WHERE id=%s",
                    [doc.pk],
                    "nep_cancelled_document_immutable",
                )

    def test_SQL31_new_request_must_start_pending(self):
        self.reject(
            "INSERT INTO store_weborder (id,code,request_key,owner_hash,payload_hash,customer_name,phone,note,status,total_amount,handled_at,reason,cancel_origin,version,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,'Khach','0901234567','','CANCELLED',100000,now(),'Huy','CUSTOMER',1,now(),now())",
            [uuid4(), "DH-INVALID", uuid4(), "a" * 64, "b" * 64],
            "nep_web_initial_state",
        )

    def test_SQL32_pending_request_cannot_contain_handled_metadata(self):
        order, _ = self.place()
        self.reject(
            "UPDATE store_weborder SET handled_at=now() WHERE id=%s",
            [order.pk],
            "nep_web_transition_valid",
        )

    def test_SQL33_document_cannot_be_inserted_as_already_cancelled(self):
        self.reject(
            "INSERT INTO store_saleorder (code,status,version,created_by_id,cancel_reason,total_amount,created_at,updated_at) VALUES ('BH-INVALID','CANCELLED',1,%s,'Huy',0,now(),now())",
            [self.admin.pk],
            "nep_document_initial_state",
        )

    def test_SQL34_accepting_request_requires_a_draft_sale(self):
        order, _ = self.place()
        sale = create_document(self.sales, "sale", {})
        cancel_draft(self.sales, "sale", sale.pk, sale.version, "Hủy kiểm thử")
        self.reject(
            "UPDATE store_weborder SET status='ACCEPTED',sale_id=%s,handled_by_id=%s,handled_at=now(),version=version+1 WHERE id=%s",
            [sale.pk, self.sales.pk, order.pk],
            "nep_web_accept_draft_sale",
        )

    def test_SQL35_document_cancellation_requires_a_reason_in_SQL(self):
        sale = create_document(self.sales, "sale", {})
        self.reject(
            "UPDATE store_saleorder SET status='CANCELLED',version=version+1 WHERE id=%s",
            [sale.pk],
            "nep_document_cancel_reason",
        )

    def test_SQL36_document_transition_must_increment_version(self):
        sale = create_document(self.sales, "sale", {})
        self.reject(
            "UPDATE store_saleorder SET status='CANCELLED',cancel_reason='Huy' WHERE id=%s",
            [sale.pk],
            "nep_document_transition_version",
        )
