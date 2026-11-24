from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from store.forecast.replenishment import (
    create_suggestion,
    evaluate_matrix,
    month_add,
    suggestion_stale,
)
from store.forms.documents import DocumentLineForm
from store.models import *
from store.services.catalog import save_catalog, save_user, set_safety_stock
from store.services.documents import *
from store.services.reports import reconciliation, sales_report


def fixture():
    admin = User.objects.create_user(
        "admin", password="Test-password-2034!", role=Role.ADMIN, full_name="Quản trị thử nghiệm"
    )
    sales = User.objects.create_user(
        "sales", password="Test-password-2034!", role=Role.SALES, full_name="Bán hàng thử nghiệm"
    )
    kho = User.objects.create_user(
        "kho", password="Test-password-2034!", role=Role.WAREHOUSE, full_name="Kho thử nghiệm"
    )
    cat = Category.objects.create(code="CAT", name="Áo")
    brand = Brand.objects.create(code="BR", name="Nhãn thử nghiệm")
    size = Size.objects.create(code="M", name="M")
    color = Color.objects.create(code="DEN", name="Đen")
    product = Product.objects.create(
        code="SP", name="Áo thử nghiệm", category=cat, brand=brand, unit="chiếc"
    )
    v = Variant.objects.create(
        product=product,
        size=size,
        color=color,
        sku="SP-M-DEN",
        selling_price=100000,
        low_stock_threshold=3,
    )
    color2 = Color.objects.create(code="TRANG", name="Trắng")
    v2 = Variant.objects.create(
        product=product, size=size, color=color2, sku="SP-M-TRANG", selling_price=120000
    )
    supplier = Supplier.objects.create(code="NCC", name="Nhà cung cấp thử nghiệm")
    SystemGuard.objects.create(pk=1)
    return admin, sales, kho, product, v, v2, supplier


class BusinessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = fixture()

    def opening(self, quantities=None):
        d = create_document(
            self.admin, "adjustment", {"kind": "OPENING", "reason": "Kiểm kê thử nghiệm"}
        )
        for v, n in quantities or [(self.v, 10)]:
            d = set_line(self.admin, "adjustment", d.pk, d.version, v, n)
        return confirm_document(self.admin, "adjustment", d.pk, d.version, uuid4())

    def sale(self, n=3, v=None, actor=None):
        actor = actor or self.sales
        d = create_document(actor, "sale", {"customer": None})
        return set_line(actor, "sale", d.pk, d.version, v or self.v, n)

    def post_sale(self, d, key=None, **pay):
        return confirm_document(
            self.sales,
            "sale",
            d.pk,
            d.version,
            key or uuid4(),
            {"method": "CASH", "cash_received": str(d.total_amount), **pay},
        )

    def receipt(self, n=5, cost=50000):
        d = create_document(self.kho, "receipt", {"supplier": self.supplier})
        return set_line(self.kho, "receipt", d.pk, d.version, self.v, n, cost)

    def test_TC01_password_is_hashed_and_login_normalized(self):
        self.assertNotEqual(self.sales.password, "Test-password-2034!")
        r = self.client.post(
            reverse("login"), {"username": " SALES ", "password": "Test-password-2034!"}
        )
        self.assertRedirects(r, reverse("dashboard"))

    def test_TC02_sales_cannot_reach_admin_or_warehouse(self):
        self.client.force_login(self.sales)
        for url in [
            reverse("employees"),
            reverse("report"),
            reverse("documents", args=["receipt"]),
            reverse("catalog_new", args=["products"]),
            reverse("audit"),
            reverse("forecasts"),
        ]:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_TC03_lock_applies_to_current_session(self):
        self.client.force_login(self.sales)
        User.objects.filter(pk=self.sales.pk).update(is_active=False)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        with self.assertRaises(PermissionDenied):
            self.sale()

    def test_TC04_last_admin_protected(self):
        values = {
            "username": "admin",
            "full_name": "Quản trị",
            "role": Role.SALES,
            "is_active": True,
        }
        with self.assertRaises(BusinessError):
            save_user(self.admin, values, self.admin.pk, 1)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, Role.ADMIN)

    def test_TC04_two_admins_allow_deactivation(self):
        User.objects.create_user("admin2", role=Role.ADMIN, password="Strong-test-7788!")
        save_user(
            self.admin,
            {"username": "admin", "full_name": "Quản trị", "role": Role.ADMIN, "is_active": False},
            self.admin.pk,
            1,
        )
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_active)

    def test_TC05_duplicate_combination_rejected_at_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Variant.objects.create(
                product=self.product,
                size=self.v.size,
                color=self.v.color,
                sku="OTHER",
                selling_price=10,
            )

    def test_TC06_inactive_variant_retains_history_blocks_new_sale(self):
        self.opening()
        Variant.objects.filter(pk=self.v.pk).update(is_active=False)
        with self.assertRaises(BusinessError):
            self.sale()
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)

    def test_TC07_anonymous_customer_and_duplicate_phone_allowed(self):
        self.assertIsNone(self.sale().customer_id)
        Customer.objects.create(code="K1", name="A", phone="0123456789")
        Customer.objects.create(code="K2", name="B", phone="0123456789")
        self.assertEqual(Customer.objects.count(), 2)

    def test_draft_header_updates_but_posted_header_is_immutable(self):
        self.opening()
        d = self.sale()
        customer = Customer.objects.create(code="KH", name="Khách thử nghiệm")
        updated = update_header(self.sales, "sale", d.pk, d.version, {"customer": customer})
        self.assertEqual(updated.customer_id, customer.pk)
        with self.assertRaises(BusinessError):
            update_header(self.sales, "sale", d.pk, d.version, {"customer": None})
        posted = self.post_sale(updated)
        with self.assertRaises(BusinessError):
            update_header(self.sales, "sale", posted.pk, posted.version, {"customer": None})

    def test_TC08_negative_fractional_quantities_rejected(self):
        for x in [-1, "1.5", 0, "NaN", "1e3"]:
            with self.assertRaises(BusinessError):
                self.receipt(x)
        self.assertEqual(StockPosting.objects.count(), 0)

    def test_TC09_receipt_retry_posts_once(self):
        self.opening()
        d = self.receipt()
        key = uuid4()
        r = confirm_document(self.kho, "receipt", d.pk, d.version, key)
        retry = confirm_document(self.kho, "receipt", d.pk, d.version, key)
        self.assertEqual(r.pk, retry.pk)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 15)
        self.assertEqual(StockPosting.objects.filter(kind="RECEIPT").count(), 1)

    def test_TC10_sale_cash_change_and_snapshot(self):
        self.opening()
        d = self.sale()
        p = self.post_sale(d, cash_received="350000")
        self.assertEqual(p.payment.change_amount, 50000)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 7)
        line = p.lines.get()
        self.assertEqual(line.sku_snapshot, self.v.sku)
        Product.objects.filter(pk=self.product.pk).update(name="Tên mới")
        line.refresh_from_db()
        self.assertEqual(line.name_snapshot, "Áo thử nghiệm")

    def test_TC10_underpaid_or_unconfirmed_transfer_rejected(self):
        self.opening()
        d = self.sale()
        for pay in [
            {"method": "CASH", "cash_received": "1"},
            {"method": "TRANSFER", "transfer_ack": False},
        ]:
            with self.assertRaises(BusinessError):
                confirm_document(self.sales, "sale", d.pk, d.version, uuid4(), pay)
        self.assertEqual(SalePayment.objects.count(), 0)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)

    def test_TC10_transfer_recorded_without_bank_claim(self):
        self.opening()
        d = self.sale()
        p = confirm_document(
            self.sales,
            "sale",
            d.pk,
            d.version,
            uuid4(),
            {"method": "TRANSFER", "transfer_ack": True, "reference": "Kiemtra"},
        )
        self.assertIsNone(p.payment.cash_received)
        self.assertEqual(p.payment.method, "TRANSFER")

    def test_TC12_missing_one_line_rolls_back_entire_document(self):
        self.opening([(self.v, 10), (self.v2, 1)])
        d = self.sale()
        d = set_line(self.sales, "sale", d.pk, d.version, self.v2, 2)
        with self.assertRaises(BusinessError):
            self.post_sale(d)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)
        self.assertEqual(StockBalance.objects.get(pk=self.v2.pk).quantity, 1)
        self.assertEqual(SalePayment.objects.count(), 0)
        self.assertFalse(StockPosting.objects.filter(kind="SALE").exists())

    def test_TC13_failure_after_balance_write_rolls_back(self):
        self.opening()
        d = self.sale()
        with patch(
            "store.services.documents.StockEntry.objects.create",
            side_effect=RuntimeError("injected"),
        ):
            with self.assertRaises(RuntimeError):
                self.post_sale(d)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)
        self.assertEqual(SalePayment.objects.count(), 0)
        self.assertFalse(AuditEvent.objects.filter(action="POST", object_type="SaleOrder").exists())

    def test_TC14_repeat_key_different_payload_conflicts(self):
        self.opening()
        d = self.sale()
        key = uuid4()
        self.post_sale(d, key)
        with self.assertRaises(BusinessError):
            self.post_sale(d, key, cash_received="900000")
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 7)

    def test_TC15_price_change_requires_review(self):
        self.opening()
        d = self.sale()
        Variant.objects.filter(pk=self.v.pk).update(selling_price=110000)
        with self.assertRaises(BusinessError):
            self.post_sale(d)
        d = refresh_prices(self.sales, d.pk, d.version)
        self.assertEqual(d.total_amount, 330000)
        self.post_sale(d)

    def test_TC16_stale_version_and_posted_cancel_rejected(self):
        self.opening()
        d = self.sale()
        stale = d.version
        d = set_line(self.sales, "sale", d.pk, d.version, self.v, 2)
        with self.assertRaises(BusinessError):
            cancel_draft(self.sales, "sale", d.pk, stale, "Sai")
        self.post_sale(d)
        with self.assertRaises(BusinessError):
            cancel_draft(self.sales, "sale", d.pk, d.version, "Sai")

    def test_TC17_cancel_and_print_do_not_change_stock(self):
        self.opening()
        d = self.sale()
        cancel_draft(self.sales, "sale", d.pk, d.version, "Không mua")
        self.client.force_login(self.sales)
        self.assertEqual(self.client.get(reverse("document", args=["sale", d.pk])).status_code, 200)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)

    def test_TC18_second_opening_even_after_zero_rejected(self):
        self.opening([(self.v, 0)])
        with self.assertRaises(BusinessError):
            self.opening([(self.v, 1)])

    def test_TC19_count_version_changed_rejected(self):
        self.opening()
        d = create_document(self.admin, "adjustment", {"kind": "COUNT", "reason": "Kiểm kê"})
        d = set_line(self.admin, "adjustment", d.pk, d.version, self.v, 8)
        self.post_sale(self.sale(1))
        with self.assertRaises(BusinessError):
            confirm_document(self.admin, "adjustment", d.pk, d.version, uuid4())
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 9)

    def test_TC20_receipt_correction_cannot_make_negative(self):
        d = self.receipt(5)
        p = confirm_document(self.kho, "receipt", d.pk, d.version, uuid4())
        self.post_sale(self.sale(2))
        with self.assertRaises(BusinessError):
            correct_document(
                self.admin, "receipt", p.pk, uuid4(), reason="Sai", evidence="Đối soát"
            )
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 3)

    def test_TC21_correction_once_with_retry_and_new_key(self):
        self.opening()
        p = self.post_sale(self.sale())
        key = uuid4()
        kwargs = {
            "reason": "Sai đơn",
            "evidence": "Đã đối soát",
            "goods_ack": True,
            "financial_ack": True,
        }
        c = correct_document(self.admin, "sale", p.pk, key, **kwargs)
        self.assertEqual(correct_document(self.admin, "sale", p.pk, key, **kwargs).pk, c.pk)
        with self.assertRaises(BusinessError):
            correct_document(self.admin, "sale", p.pk, uuid4(), **kwargs)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)

    def test_TC22_missing_recovery_or_financial_ack_blocks(self):
        self.opening()
        p = self.post_sale(self.sale())
        with self.assertRaises(BusinessError):
            correct_document(
                self.admin,
                "sale",
                p.pk,
                uuid4(),
                reason="Sai",
                evidence="Kiểm tra",
                goods_ack=False,
                financial_ack=True,
            )

    def test_TC23_report_not_double_count_and_separate_correction_period(self):
        old = timezone.make_aware(datetime(2026, 1, 30, 9))
        with patch("store.services.documents.timezone.now", return_value=old):
            self.opening([(self.v, 10), (self.v2, 10)])
            d = self.sale(1)
            d = set_line(self.sales, "sale", d.pk, d.version, self.v2, 2)
            p = self.post_sale(d)
        correct_document(
            self.admin,
            "sale",
            p.pk,
            uuid4(),
            reason="Sai",
            evidence="Kiểm tra",
            goods_ack=True,
            financial_ack=True,
        )
        january = sales_report(self.admin, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(january["orders"], 1)
        self.assertEqual(january["gross"], 340000)
        today = timezone.localdate()
        now = sales_report(self.admin, today, today)
        self.assertEqual(now["correction"], 340000)
        self.assertEqual(now["orders"], 0)

    def test_TC24_vietnam_midnight_boundaries(self):
        with patch(
            "store.services.documents.timezone.now",
            return_value=timezone.make_aware(datetime(2026, 1, 31, 23, 59)),
        ):
            self.opening()
            self.post_sale(self.sale(1))
        with patch(
            "store.services.documents.timezone.now",
            return_value=timezone.make_aware(datetime(2026, 2, 1, 0, 0)),
        ):
            self.post_sale(self.sale(1))
        self.assertEqual(
            sales_report(self.admin, date(2026, 1, 31), date(2026, 1, 31))["orders"], 1
        )
        self.assertEqual(sales_report(self.admin, date(2026, 2, 1), date(2026, 2, 1))["orders"], 1)

    def forecast_value(self, source="OPERATIONAL", forecast="32.4"):
        month = timezone.localdate().replace(day=1)
        ds = DatasetVersion.objects.create(
            code=uuid4().hex,
            source_type=source,
            manifest_hash="a" * 64,
            coverage_start=month_add(month, -19),
            coverage_end=month_add(month, -1),
            status="VALIDATED",
            created_by=self.admin,
        )
        unit = ForecastUnit.objects.create(
            dataset_version=ds,
            external_key="P1",
            granularity="PRODUCT",
            unit="chiếc",
            scope_key="STORE_MAIN",
            internal_product=self.product,
            mapping_status="VERIFIED",
        )
        ex = Experiment.objects.create(dataset_version=ds, status="SUCCEEDED")
        model = ModelResult.objects.create(
            experiment=ex, method="naive", selected_on_validation=True
        )
        run = ForecastRun.objects.create(
            model_result=model,
            cutoff_month=month_add(month, -1),
            target_month=month,
            scope_key="STORE_MAIN",
            status="SUCCEEDED",
        )
        return ForecastValue.objects.create(
            run=run,
            forecast_unit=unit,
            raw_value=forecast,
            nonnegative_value=forecast,
            result_status="VALID",
        )

    def test_TC29_suggestion_rounds_whole_expression(self):
        self.opening([(self.v, 20)])
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.forecast_value()
        s = create_suggestion(self.admin, value.pk)
        self.assertEqual(s.suggested_qty, 18)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 20)
        value.nonnegative_value = 1
        value.save()
        self.assertEqual(create_suggestion(self.admin, value.pk).suggested_qty, 0)

    def test_TC30_research_mapping_and_wrong_month_blocked(self):
        set_safety_stock(self.admin, self.product.pk, 5)
        v = self.forecast_value("RESEARCH")
        with self.assertRaises(BusinessError):
            create_suggestion(self.admin, v.pk)
        v = self.forecast_value()
        v.run.cutoff_month = date(2023, 7, 1)
        v.run.target_month = date(2023, 8, 1)
        v.run.save()
        with self.assertRaises(BusinessError):
            create_suggestion(self.admin, v.pk)
        v = self.forecast_value()
        v.forecast_unit.mapping_status = "UNVERIFIED"
        v.forecast_unit.save()
        with self.assertRaises(BusinessError):
            create_suggestion(self.admin, v.pk)

    def test_TC31_balance_or_policy_change_marks_stale(self):
        self.opening()
        set_safety_stock(self.admin, self.product.pk, 5)
        v = self.forecast_value()
        s = create_suggestion(self.admin, v.pk)
        self.assertFalse(suggestion_stale(s))
        self.post_sale(self.sale(1))
        self.assertTrue(suggestion_stale(s))
        s = create_suggestion(self.admin, v.pk)
        set_safety_stock(self.admin, self.product.pk, 6)
        self.assertTrue(suggestion_stale(s))

    def test_TC33_other_employee_document_denied(self):
        d = self.sale()
        other = User.objects.create_user("other", role=Role.SALES)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("document", args=["sale", d.pk])).status_code, 403)
        with self.assertRaises(PermissionDenied):
            set_line(other, "sale", d.pk, d.version, self.v, 1)

    def test_TC35_ledger_balances_reconcile(self):
        self.opening()
        p = self.post_sale(self.sale())
        correct_document(
            self.admin,
            "sale",
            p.pk,
            uuid4(),
            reason="Sai",
            evidence="Kiểm tra",
            goods_ack=True,
            financial_ack=True,
        )
        self.assertFalse(reconciliation(self.admin).exists())

    def test_zero_count_form_valid_and_unknown_negative_distinct(self):
        form = DocumentLineForm(
            {"version": 1, "variant": self.v.pk, "quantity": 0}, kind="adjustment"
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(
            DocumentLineForm(
                {"version": 1, "variant": self.v.pk, "quantity": 0}, kind="sale"
            ).is_valid()
        )

    def test_TC34_all_key_pages_render_and_csrf_protected(self):
        self.opening()
        d = self.sale()
        self.client.force_login(self.admin)
        urls = [
            reverse("dashboard"),
            reverse("employees"),
            reverse("employee_new"),
            reverse("report"),
            reverse("inventory"),
            reverse("ledger", args=[self.v.pk]),
            reverse("forecasts"),
            reverse("audit"),
            reverse("guide"),
            reverse("document", args=["sale", d.pk]),
        ]
        urls += [
            reverse("catalog", args=[k])
            for k in [
                "products",
                "variants",
                "categories",
                "brands",
                "sizes",
                "colors",
                "customers",
                "suppliers",
            ]
        ]
        urls += [
            reverse("catalog_new", args=[k])
            for k in ["products", "variants", "customers", "suppliers"]
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.sales)
        self.assertEqual(
            secure.post(
                reverse("document_action", args=["sale", d.pk]), {"action": "confirm"}
            ).status_code,
            403,
        )


class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.sales, self.kho, self.product, self.v, self.v2, self.supplier = fixture()
        self.other = User.objects.create_user("other", role=Role.SALES)
        d = create_document(
            self.admin, "adjustment", {"kind": "OPENING", "reason": "Thử đồng thời"}
        )
        d = set_line(self.admin, "adjustment", d.pk, d.version, self.v, 1)
        confirm_document(self.admin, "adjustment", d.pk, d.version, uuid4())

    def test_TC11_two_connections_last_unit_only_one_succeeds(self):
        self.assertEqual(connections["default"].vendor, "postgresql")
        docs = []
        for actor in [self.sales, self.other]:
            d = create_document(actor, "sale", {"customer": None})
            d = set_line(actor, "sale", d.pk, d.version, self.v, 1)
            docs.append((actor.pk, d.pk, d.version))
        barrier = Barrier(2)

        def worker(args):
            connections.close_all()
            try:
                uid, did, version = args
                u = User.objects.get(pk=uid)
                barrier.wait(timeout=10)
                confirm_document(
                    u, "sale", did, version, uuid4(), {"method": "CASH", "cash_received": "100000"}
                )
                return "ok"
            except BusinessError:
                return "insufficient"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(worker, docs))
        self.assertCountEqual(results, ["ok", "insufficient"])
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 0)
        self.assertEqual(SaleOrder.objects.filter(status="POSTED").count(), 1)

    def test_TC14_two_connections_same_actor_request_same_result(self):
        d = create_document(self.sales, "sale", {"customer": None})
        d = set_line(self.sales, "sale", d.pk, d.version, self.v, 1)
        key = uuid4()
        barrier = Barrier(2)

        def worker(_):
            connections.close_all()
            try:
                u = User.objects.get(pk=self.sales.pk)
                barrier.wait(timeout=10)
                return confirm_document(
                    u, "sale", d.pk, d.version, key, {"method": "CASH", "cash_received": "100000"}
                ).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as ex:
            ids = list(ex.map(worker, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(StockPosting.objects.filter(kind="SALE").count(), 1)
