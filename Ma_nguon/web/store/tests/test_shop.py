import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from store.models import *
from store.services.documents import BusinessError, confirm_document, create_document, set_line
from store.services.orders import accept_order, cancel_order, submit_order
from store.tests.test_business import fixture


def stock(admin, v, n=8):
    d = create_document(admin, "adjustment", {"kind": "OPENING", "reason": "Dữ liệu kiểm thử Web"})
    d = set_line(admin, "adjustment", d.pk, d.version, v, n)
    confirm_document(admin, "adjustment", d.pk, d.version, uuid4())


def count_stock(admin, v, n):
    d = create_document(
        admin, "adjustment", {"kind": "COUNT", "reason": "Kiểm đếm dữ liệu kiểm thử Web"}
    )
    d = set_line(admin, "adjustment", d.pk, d.version, v, n)
    confirm_document(admin, "adjustment", d.pk, d.version, uuid4())


class ShopTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = fixture()
        stock(cls.admin, cls.v)
        stock(cls.admin, cls.v2)

    def add(self, client=None, v=None, n=1):
        c = client or self.client
        return c.post(
            reverse("shop_cart_action"),
            {"action": "add", "variant_id": (v or self.v).pk, "quantity": n},
        )

    def prepare(self, client=None):
        c = client or self.client
        self.add(c)
        response = c.get(reverse("shop_checkout"))
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        return {
            "customer_name": "Khách kiểm thử",
            "phone": "0900000000",
            "payment_method": "CASH",
            "note": "Dữ liệu thử, không phải người thật",
            "request_key": str(form.initial["request_key"]),
            "quote": form.initial["quote"],
        }

    def place(self):
        data = self.prepare()
        r = self.client.post(reverse("shop_checkout"), data)
        self.assertEqual(r.status_code, 302)
        return WebOrder.objects.get(), data

    def test_SH01_catalogue_public_and_staff_dashboard_remains_private(self):
        for route in [
            reverse("shop_home"),
            reverse("shop_catalogue"),
            reverse("shop_product", args=[self.product.pk]),
            reverse("shop_cart"),
            reverse("shop_orders"),
        ]:
            self.assertEqual(self.client.get(route).status_code, 200, route)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        self.assertEqual(SaleOrder.objects.count(), 0)

    def test_SH02_filter_uses_same_variant_for_size_color_and_stock(self):
        size = Size.objects.create(code="L", name="L")
        v = Variant.objects.create(
            product=self.product, size=size, color=self.v.color, sku="SP-L-DEN", selling_price=90000
        )
        stock(self.admin, v)
        qs = {"size": "L", "color": "TRANG", "stock": "1"}
        self.assertEqual(
            self.client.get(reverse("shop_catalogue"), qs).context["page"].paginator.count, 0
        )
        qs["color"] = "DEN"
        self.assertEqual(
            self.client.get(reverse("shop_catalogue"), qs).context["page"].paginator.count, 1
        )

    def test_SH03_inactive_or_zero_price_variant_cannot_be_added(self):
        Variant.objects.filter(pk=self.v.pk).update(is_active=False)
        self.add()
        self.assertEqual(self.client.session.get("nep_cart", {}), {})
        Variant.objects.filter(pk=self.v.pk).update(is_active=True, selling_price=0)
        self.add()
        self.assertEqual(self.client.session.get("nep_cart", {}), {})

    def test_SH04_negative_fractional_excessive_quantity_and_get_rejected(self):
        for n in [-1, "1.5", 99, 0]:
            self.add(n=n)
        self.assertEqual(self.client.session.get("nep_cart", {}), {})
        self.assertEqual(self.client.get(reverse("shop_cart_action")).status_code, 405)

    def test_SH05_update_remove_cart_without_inventory_change(self):
        self.add(n=2)
        self.add(n=2)
        self.assertEqual(self.client.session["nep_cart"][str(self.v.pk)], 4)
        self.client.post(
            reverse("shop_cart_action"),
            {"action": "update", "variant_id": self.v.pk, "quantity": 3},
        )
        self.assertEqual(self.client.get(reverse("shop_cart")).context["total"], 300000)
        self.client.post(reverse("shop_cart_action"), {"action": "remove", "variant_id": self.v.pk})
        self.assertFalse(self.client.session["nep_cart"])
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 8)

    def test_SH06_guest_order_is_real_record_but_not_sale_payment_or_stock(self):
        before = StockEntry.objects.count()
        order, data = self.place()
        self.assertEqual(order.total_amount, 100000)
        self.assertEqual(order.lines.count(), 1)
        self.assertEqual(order.status, "PENDING")
        self.assertEqual(SaleOrder.objects.count(), 0)
        self.assertEqual(SalePayment.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(StockEntry.objects.count(), before)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 8)
        self.assertContains(self.client.get(reverse("shop_order", args=[order.pk])), order.code)

    def test_SH07_retry_same_submission_creates_only_one_order(self):
        order, data = self.place()
        r = self.client.post(reverse("shop_checkout"), data)
        self.assertRedirects(r, reverse("shop_order", args=[order.pk]))
        self.assertEqual(WebOrder.objects.count(), 1)
        self.assertEqual(WebOrderLine.objects.count(), 1)

    def test_SH08_same_key_with_changed_contact_is_rejected(self):
        order, data = self.place()
        data["customer_name"] = "Khách khác"
        r = self.client.post(reverse("shop_checkout"), data)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["form"].non_field_errors())
        self.assertEqual(WebOrder.objects.count(), 1)

    def test_SH09_order_private_to_guest_session(self):
        order, data = self.place()
        other = Client()
        self.assertEqual(other.get(reverse("shop_order", args=[order.pk])).status_code, 404)
        self.assertNotContains(other.get(reverse("shop_orders")), order.code)
        self.assertEqual(
            other.post(reverse("shop_cancel", args=[order.pk]), {"version": 1}).status_code, 404
        )

    def test_SH10_signed_quote_tamper_and_expired_quote_rejected(self):
        data = self.prepare()
        with patch("django.core.signing.time.time", return_value=time.time() + 3700):
            r = self.client.post(reverse("shop_checkout"), data)
        self.assertTrue(r.context["form"].non_field_errors())
        self.assertFalse(WebOrder.objects.exists())
        data["quote"] = data["quote"][:-8] + "changed"
        r = self.client.post(reverse("shop_checkout"), data)
        self.assertTrue(r.context["form"].non_field_errors())
        self.assertFalse(WebOrder.objects.exists())

    def test_SH11_price_or_stock_changed_after_checkout_blocks_submission(self):
        data = self.prepare()
        Variant.objects.filter(pk=self.v.pk).update(selling_price=110000)
        r = self.client.post(reverse("shop_checkout"), data)
        self.assertTrue(r.context["form"].non_field_errors())
        self.assertFalse(WebOrder.objects.exists())
        Variant.objects.filter(pk=self.v.pk).update(selling_price=100000)
        count_stock(self.admin, self.v, 0)
        r = self.client.post(reverse("shop_checkout"), data)
        self.assertTrue(r.context["form"].non_field_errors())
        self.assertFalse(WebOrder.objects.exists())

    def test_SH12_cart_changed_after_checkout_requires_review(self):
        data = self.prepare()
        self.add(v=self.v2)
        r = self.client.post(reverse("shop_checkout"), data)
        self.assertTrue(r.context["form"].non_field_errors())
        self.assertFalse(WebOrder.objects.exists())

    def test_SH13_bad_phone_and_empty_name_rejected(self):
        data = self.prepare()
        data.update(phone="hello", customer_name="")
        r = self.client.post(reverse("shop_checkout"), data)
        self.assertIn("phone", r.context["form"].errors)
        self.assertIn("customer_name", r.context["form"].errors)
        self.assertFalse(WebOrder.objects.exists())

    def test_SH14_public_mutations_csrf_protected(self):
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(
            c.post(
                reverse("shop_cart_action"),
                {"action": "add", "variant_id": self.v.pk, "quantity": 1},
            ).status_code,
            403,
        )
        self.assertEqual(c.post(reverse("shop_checkout"), {}).status_code, 403)

    def test_SH15_staff_acceptance_creates_one_draft_preserves_stock(self):
        order, data = self.place()
        accepted = accept_order(self.sales, order.pk, 1)
        again = accept_order(self.sales, order.pk, 1)
        self.assertEqual(accepted.sale_id, again.sale_id)
        self.assertEqual(SaleOrder.objects.count(), 1)
        self.assertEqual(accepted.sale.status, Status.DRAFT)
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 8)
        self.assertEqual(SalePayment.objects.count(), 0)

    def test_SH16_warehouse_denied_at_url_and_service(self):
        order, data = self.place()
        self.client.force_login(self.kho)
        for url in [reverse("web_orders"), reverse("web_order", args=[order.pk])]:
            self.assertEqual(self.client.get(url).status_code, 403)
        with self.assertRaises(PermissionDenied):
            accept_order(self.kho, order.pk, 1)

    def test_SH17_acceptance_rechecks_stock_without_partial_customer_or_sale(self):
        order, data = self.place()
        count_stock(self.admin, self.v, 0)
        with self.assertRaises(BusinessError):
            accept_order(self.sales, order.pk, 1)
        self.assertFalse(SaleOrder.objects.exists())
        self.assertFalse(Customer.objects.exists())
        order.refresh_from_db()
        self.assertEqual(order.status, "PENDING")

    def test_SH18_staff_price_change_requires_explicit_acknowledgement(self):
        order, data = self.place()
        Variant.objects.filter(pk=self.v.pk).update(selling_price=110000)
        with self.assertRaises(BusinessError):
            accept_order(self.sales, order.pk, 1)
        order = accept_order(self.sales, order.pk, 1, True)
        self.assertEqual(order.total_amount, 100000)
        self.assertEqual(order.sale.total_amount, 110000)

    def test_SH19_guest_cancellation_only_pending_and_never_changes_stock(self):
        order, data = self.place()
        url = reverse("shop_cancel", args=[order.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {"version": 1})
        order.refresh_from_db()
        self.assertEqual(order.status, "CANCELLED")
        self.assertEqual(order.cancel_origin, "CUSTOMER")
        with self.assertRaises(BusinessError):
            accept_order(self.sales, order.pk, 2)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 8)

    def test_SH20_posted_sale_is_only_point_where_stock_reduces(self):
        order, data = self.place()
        order = accept_order(self.sales, order.pk, 1)
        sale = order.sale
        confirm_document(
            self.sales,
            "sale",
            sale.pk,
            sale.version,
            uuid4(),
            payment={"method": "CASH", "cash_received": "100000"},
        )
        order = WebOrder.objects.select_related("sale").get(pk=order.pk)
        self.assertEqual(order.display_status, "Đã hoàn tất tại cửa hàng")
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 7)
        self.assertEqual(SalePayment.objects.count(), 1)

    def test_SH21_staff_cancellation_reason_and_html_escaping(self):
        order, data = self.place()
        with self.assertRaises(BusinessError):
            cancel_order(order.pk, 1, actor=self.sales)
        cancel_order(order.pk, 1, actor=self.sales, reason="<script>alert(1)</script>")
        r = self.client.get(reverse("shop_order", args=[order.pk]))
        self.assertNotContains(r, "<script>alert(1)</script>")
        self.assertContains(r, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_SH22_incoming_views_render_and_guest_detail_not_cached(self):
        order, data = self.place()
        self.assertIn(
            "no-store", self.client.get(reverse("shop_order", args=[order.pk]))["Cache-Control"]
        )
        self.client.force_login(self.sales)
        for url in [reverse("web_orders"), reverse("web_order", args=[order.pk])]:
            self.assertEqual(self.client.get(url).status_code, 200)


class ShopConcurrencyTests(TransactionTestCase):
    def test_SH23_two_staff_accepting_same_request_create_only_one_sale(self):
        admin, sales, kho, p, v, v2, supplier = fixture()
        stock(admin, v)
        other = User.objects.create_user("sales2", role=Role.SALES)
        order, _ = submit_order(
            "x" * 64,
            uuid4(),
            [[v.pk, 1, "100000"]],
            {"customer_name": "Tình huống đồng thời", "phone": "0900000000", "note": ""},
        )
        barrier = Barrier(2)

        def worker(pk):
            connections.close_all()
            try:
                actor = User.objects.get(pk=pk)
                barrier.wait(timeout=8)
                try:
                    return ("ok", str(accept_order(actor, order.pk, 1).sale_id))
                except BusinessError:
                    return ("blocked", None)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(worker, [sales.pk, other.pk]))
        self.assertEqual(sorted(r[0] for r in result), ["blocked", "ok"])
        self.assertEqual(SaleOrder.objects.count(), 1)
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(StockBalance.objects.get(pk=v.pk).quantity, 8)
