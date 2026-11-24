"""Integrated exception paths using PostgreSQL and disposable test records."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.db import connections
from django.test import TestCase, TransactionTestCase

from store.models import (
    Customer,
    Role,
    SaleOrder,
    SalePayment,
    Status,
    StockBalance,
    StockEntry,
    User,
    WebOrder,
)
from store.services.documents import (
    BusinessError,
    cancel_draft,
    confirm_document,
    create_document,
    refresh_prices,
    set_line,
)
from store.services.orders import accept_order, cancel_order, submit_order
from store.tests.test_business import fixture
from store.tests.test_shop import stock


def request(v, owner="r" * 64):
    return submit_order(
        owner,
        uuid4(),
        [[v.pk, 1, "100000"]],
        {
            "customer_name": "Khách kiểm thử nghiệp vụ",
            "phone": "0900000000",
            "note": "",
        },
    )[0]


def pay(actor, sale, amount="100000", key=None):
    return confirm_document(
        actor,
        "sale",
        sale.pk,
        sale.version,
        key or uuid4(),
        {"method": "CASH", "cash_received": amount},
    )


class RealWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = fixture()
        stock(cls.admin, cls.v, 1)

    def test_RT01_counter_sale_can_exhaust_accepted_web_order_without_partial_payment(
        self,
    ):
        order = accept_order(self.sales, request(self.v).pk, 1)
        counter = create_document(self.admin, "sale", {})
        counter = set_line(self.admin, "sale", counter.pk, counter.version, self.v, 1)
        pay(self.admin, counter)
        entries = StockEntry.objects.count()
        with self.assertRaisesMessage(BusinessError, "không đủ tồn"):
            pay(self.sales, order.sale)
        order.refresh_from_db()
        self.assertEqual(order.lifecycle_status, "ACCEPTED")
        self.assertEqual(SaleOrder.objects.get(pk=order.sale_id).status, Status.DRAFT)
        self.assertEqual(SalePayment.objects.count(), 1)
        self.assertFalse(SalePayment.objects.filter(sale_id=order.sale_id).exists())
        self.assertEqual(StockEntry.objects.count(), entries)
        self.assertEqual(StockBalance.objects.get(variant=self.v).quantity, 0)

    def test_RT02_price_change_after_acceptance_requires_review_and_updated_payment(
        self,
    ):
        order = accept_order(self.sales, request(self.v).pk, 1)
        type(self.v).objects.filter(pk=self.v.pk).update(selling_price=130000)
        with self.assertRaisesMessage(BusinessError, "giá bán đã thay đổi"):
            pay(self.sales, order.sale)
        self.assertFalse(SalePayment.objects.exists())
        sale = refresh_prices(self.sales, order.sale_id, order.sale.version)
        with self.assertRaisesMessage(BusinessError, "chưa đủ"):
            pay(self.sales, sale)
        posted = pay(self.sales, sale, "150000")
        payment = SalePayment.objects.get(sale=posted)
        self.assertEqual((payment.amount, payment.change_amount), (130000, 20000))
        order.refresh_from_db()
        self.assertEqual(order.total_amount, 100000)
        self.assertEqual(order.lines.get().unit_price, 100000)
        self.assertEqual(order.lifecycle_status, "COMPLETED")

    def test_RT03_discontinued_product_blocks_posting_but_allows_cancelling_draft(self):
        order = accept_order(self.sales, request(self.v).pk, 1)
        type(self.product).objects.filter(pk=self.product.pk).update(is_active=False)
        with self.assertRaisesMessage(BusinessError, "ngừng sử dụng"):
            pay(self.sales, order.sale)
        cancel_draft(self.sales, "sale", order.sale_id, order.sale.version, "Mặt hàng ngừng bán")
        order.refresh_from_db()
        self.assertEqual(order.lifecycle_status, "SALE_CANCELLED")
        self.assertFalse(SalePayment.objects.exists())
        self.assertEqual(StockBalance.objects.get(variant=self.v).quantity, 1)

    def test_RT04_failed_acceptance_rolls_back_customer_draft_and_request_state(self):
        order = request(self.v)
        with patch("store.services.orders.audit", side_effect=RuntimeError("test only")):
            with self.assertRaises(RuntimeError):
                accept_order(self.sales, order.pk, 1)
        order.refresh_from_db()
        self.assertEqual((order.status, order.version, order.sale_id), ("PENDING", 1, None))
        self.assertFalse(Customer.objects.exists())
        self.assertFalse(SaleOrder.objects.exists())
        self.assertFalse(SalePayment.objects.exists())

    def test_RT05_customer_cannot_cancel_accepted_request_staff_records_no_show(self):
        order = request(self.v)
        order = accept_order(self.sales, order.pk, 1)
        with self.assertRaisesMessage(BusinessError, "còn chờ xác nhận"):
            cancel_order(order.pk, order.version, owner=order.owner_hash)
        cancel_draft(
            self.sales,
            "sale",
            order.sale_id,
            order.sale.version,
            "Khách không đến nhận",
        )
        self.assertEqual(WebOrder.objects.get(pk=order.pk).lifecycle_status, "SALE_CANCELLED")
        self.assertEqual(StockBalance.objects.get(variant=self.v).quantity, 1)
        self.assertFalse(SalePayment.objects.exists())

    def test_RT06_lost_response_retry_uses_one_payment_and_one_stock_movement(self):
        order = accept_order(self.sales, request(self.v).pk, 1)
        key = uuid4()
        before = StockEntry.objects.count()
        first = pay(self.sales, order.sale, key=key)
        retried = pay(self.sales, order.sale, key=key)
        self.assertEqual(first.pk, retried.pk)
        self.assertEqual(SalePayment.objects.count(), 1)
        self.assertEqual(StockEntry.objects.count(), before + 1)
        self.assertEqual(StockBalance.objects.get(variant=self.v).quantity, 0)


class RealWorkflowConcurrencyTests(TransactionTestCase):
    def setUp(self):
        (
            self.admin,
            self.sales,
            self.kho,
            self.product,
            self.v,
            self.v2,
            self.supplier,
        ) = fixture()
        stock(self.admin, self.v, 1)

    def test_RT07_two_accepted_web_orders_compete_for_one_unit(self):
        other = User.objects.create_user("other_sales", role=Role.SALES)
        orders = [
            accept_order(self.sales, request(self.v, "a" * 64).pk, 1),
            accept_order(other, request(self.v, "b" * 64).pk, 1),
        ]
        barrier = Barrier(2)

        def worker(pair):
            actor_id, sale_id = pair
            connections.close_all()
            try:
                actor = User.objects.get(pk=actor_id)
                sale = SaleOrder.objects.get(pk=sale_id)
                barrier.wait(timeout=10)
                try:
                    pay(actor, sale)
                    return "posted"
                except BusinessError:
                    return "blocked"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    worker,
                    [(self.sales.pk, orders[0].sale_id), (other.pk, orders[1].sale_id)],
                )
            )
        self.assertCountEqual(results, ["posted", "blocked"])
        self.assertEqual(SalePayment.objects.count(), 1)
        self.assertEqual(StockBalance.objects.get(variant=self.v).quantity, 0)
        self.assertCountEqual(
            list(WebOrder.objects.with_lifecycle().values_list("_db_lifecycle_status", flat=True)),
            ["COMPLETED", "ACCEPTED"],
        )

    def test_RT08_customer_cancelling_while_staff_accepts_never_leaves_orphan_sale(
        self,
    ):
        order = request(self.v)
        barrier = Barrier(2)

        def worker(action):
            connections.close_all()
            try:
                actor = User.objects.get(pk=self.sales.pk)
                barrier.wait(timeout=10)
                try:
                    if action == "accept":
                        accept_order(actor, order.pk, 1)
                    else:
                        cancel_order(order.pk, 1, owner=order.owner_hash)
                    return "ok"
                except BusinessError:
                    return "blocked"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(worker, ["accept", "cancel"])), ["ok", "blocked"])
        order.refresh_from_db()
        accepted = order.status == "ACCEPTED"
        self.assertIn(order.status, ["ACCEPTED", "CANCELLED"])
        self.assertEqual(SaleOrder.objects.count(), int(accepted))
        self.assertEqual(Customer.objects.count(), int(accepted))
        self.assertEqual(order.sale_id is not None, accepted)
        self.assertEqual(StockBalance.objects.get(variant=self.v).quantity, 1)
        self.assertFalse(SalePayment.objects.exists())
