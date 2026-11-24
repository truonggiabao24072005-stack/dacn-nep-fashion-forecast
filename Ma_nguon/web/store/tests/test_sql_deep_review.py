"""Regression cases for SQL paths found during the detailed review."""

from uuid import uuid4

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from store.models import Variant, WebOrder, WebOrderLine
from store.services.documents import create_document, set_line
from store.tests.test_business import fixture


class SQLDeepReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = fixture()

    def rejected(self, query, params):
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(query, params)
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")

    def web(self):
        order = WebOrder.objects.create(
            code="DH-" + uuid4().hex[:14],
            request_key=uuid4(),
            owner_hash="a" * 64,
            payload_hash="b" * 64,
            customer_name="Khách thử",
            phone="0901234567",
            total_amount=100000,
        )
        WebOrderLine.objects.create(
            order=order,
            variant=self.v,
            quantity=1,
            unit_price=100000,
            name_snapshot=self.product.name,
            sku_snapshot=self.v.sku,
            variant_snapshot="M/Đen",
        )
        return order

    def sale(self):
        doc = create_document(self.sales, "sale", {})
        return set_line(self.sales, "sale", doc.pk, doc.version, self.v, 1)

    def test_SQL21_web_total_must_match_its_lines(self):
        order = self.web()
        self.rejected(
            "UPDATE store_weborder SET total_amount=total_amount+1 WHERE id=%s", [order.pk]
        )

    def test_SQL22_web_request_cannot_have_no_lines(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            WebOrder.objects.create(
                code="DH-EMPTY",
                request_key=uuid4(),
                owner_hash="a" * 64,
                payload_hash="b" * 64,
                customer_name="Khách thử",
                phone="0901234567",
                total_amount=100000,
            )
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_SQL23_submitted_web_lines_are_immutable(self):
        order = self.web()
        self.rejected("UPDATE store_weborderline SET quantity=2 WHERE order_id=%s", [order.pk])
        self.rejected("DELETE FROM store_weborderline WHERE order_id=%s", [order.pk])

    def test_SQL24_submitted_contact_is_a_snapshot(self):
        order = self.web()
        self.rejected("UPDATE store_weborder SET customer_name='Rewritten' WHERE id=%s", [order.pk])

    def test_SQL25_draft_line_cannot_be_moved_to_another_document(self):
        first = self.sale()
        second = create_document(self.sales, "sale", {})
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE store_saleline SET sale_id=%s WHERE sale_id=%s", [second.pk, first.pk]
            )
            cursor.execute(
                "UPDATE store_saleorder SET total_amount=100000 WHERE id=%s", [second.pk]
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_SQL26_balance_cannot_be_reassigned_to_a_different_variant(self):
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM store_stockbalance WHERE variant_id=%s", [self.v2.pk])
            cursor.execute(
                "UPDATE store_stockbalance SET variant_id=%s WHERE variant_id=%s",
                [self.v2.pk, self.v.pk],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_SQL27_web_reference_preserves_variant_identity(self):
        self.web()
        self.rejected("UPDATE store_variant SET sku='CHANGED-WEB-SKU' WHERE id=%s", [self.v.pk])
