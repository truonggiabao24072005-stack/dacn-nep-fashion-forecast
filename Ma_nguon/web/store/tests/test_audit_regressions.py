from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from store.forms.employees import EmployeeForm
from store.forms.reports import DateRangeForm
from store.models import *
from store.services.catalog import save_user
from store.services.documents import BusinessError, create_document, quantity, set_line
from store.services.orders import submit_order
from store.services.reports import period_bounds
from store.tests.test_business import fixture
from store.tests.test_shop import stock


class AuditRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.variant, _, _ = fixture()
        stock(cls.admin, cls.variant)
        cls.sale = create_document(cls.admin, "sale", {})
        cls.sale = set_line(cls.admin, "sale", cls.sale.pk, cls.sale.version, cls.variant, 1)

    def test_AU01_invalid_dataset_identifiers_do_not_crash_forecasts(self):
        self.client.force_login(self.admin)
        for value in ["²", "9" * 5000, "9223372036854775808", "-1", "0"]:
            with self.subTest(length=len(value)):
                self.assertEqual(
                    self.client.get(reverse("forecasts"), {"dataset": value}).status_code, 200
                )

    def test_AU02_date_inputs_render_iso_values_for_browser_date_controls(self):
        form = DateRangeForm(
            initial={"start": date(2026, 10, 1), "end": date(2026, 10, 25), "group": "day"}
        )
        self.assertIn('value="2026-10-01"', str(form["start"]))
        self.assertIn('value="2026-10-25"', str(form["end"]))

    def test_AU03_unrepresentable_report_end_is_a_form_error(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("report"), {"start": "9999-12-31", "end": "9999-12-31", "group": "day"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        with self.assertRaises(BusinessError):
            period_bounds(date.max, date.max)

    def test_AU04_employee_login_avoids_self_redirect_loops(self):
        self.client.force_login(self.admin)
        for target in ["/dang-nhap/", "/dang-nhap/?from=test", "/dang-nhap", "/%64ang-nhap/"]:
            with self.subTest(target=target):
                response = self.client.get(reverse("login"), {"next": target})
                self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)

    def test_AU05_null_search_parameters_return_400_without_database_errors(self):
        self.client.force_login(self.admin)
        for path in ["/san-pham/", "/ton-kho/", "/danh-muc/products/", "/du-bao/"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, {"q": "x\x00y"}).status_code, 400)
        self.assertEqual(self.client.get("/san-pham/", {"q": "Áo"}).status_code, 200)

    def test_AU06_removing_line_with_invalid_identifier_preserves_document(self):
        self.client.force_login(self.admin)
        for value in ["abc", "", "9" * 5000]:
            with self.subTest(length=len(value)):
                response = self.client.post(
                    reverse("document_action", args=["sale", self.sale.pk]),
                    {"action": "remove", "variant": value, "version": self.sale.version},
                )
                self.assertEqual(response.status_code, 404)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.lines.count(), 1)
        self.assertEqual(self.sale.total_amount, 100000)

    def test_AU07_long_cart_identifiers_and_quantities_do_not_change_stock(self):
        self.client = Client(raise_request_exception=False)
        before = list(StockBalance.objects.values_list("variant_id", "quantity", "version"))
        for payload in [
            {"variant_id": "9" * 5000, "quantity": "1"},
            {"variant_id": str(self.variant.pk), "quantity": "9" * 5000},
        ]:
            with self.subTest(
                large_field="variant_id" if len(payload["variant_id"]) > 20 else "quantity"
            ):
                response = self.client.post(reverse("shop_cart_action"), payload)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.client.session.get("nep_cart", {}), {})
        self.assertEqual(
            before, list(StockBalance.objects.values_list("variant_id", "quantity", "version"))
        )

    def test_AU08_numeric_inputs_normalize_leading_zeroes_without_orphan_cart_rows(self):
        self.assertEqual(quantity("0" * 5000 + "2"), 2)
        with self.assertRaises(BusinessError):
            quantity("9" * 5000)
        self.client.post(
            reverse("shop_cart_action"),
            {"variant_id": "000" + str(self.variant.pk), "quantity": "2"},
        )
        self.assertEqual(self.client.session["nep_cart"], {str(self.variant.pk): 2})
        response = self.client.get(reverse("shop_cart"))
        self.assertTrue(response.context["ready"])
        self.assertEqual(response.context["total"], 200000)

    def test_AU09_long_staff_cancellation_reason_is_rejected_without_changing_order(self):
        order, _ = submit_order(
            "a" * 64,
            uuid4(),
            [[self.variant.pk, 1, "100000"]],
            {"customer_name": "Khách thử", "phone": "0900000000"},
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("web_order", args=[order.pk]),
            {"action": "cancel", "version": 1, "reason": "x" * 1001},
        )
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, "PENDING")
        self.assertEqual(order.version, 1)
        self.assertEqual(SalePayment.objects.count(), 0)

    def test_AU10_employee_password_preserves_the_characters_entered(self):
        password = "  Staff-secret-2042!  "
        form = EmployeeForm(
            {
                "username": "staff_space",
                "full_name": "Nhân viên thử",
                "role": Role.SALES,
                "is_active": "on",
                "new_password": password,
                "version": 1,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = save_user(self.admin, form.cleaned_data)
        self.assertTrue(user.check_password(password))

    def test_AU11_staff_login_limits_failed_attempts_and_allows_retry_after_window(self):
        payload = {"username": self.admin.username, "password": "incorrect"}
        for _ in range(8):
            self.client.post(reverse("login"), payload)
        correct = {"username": self.admin.username, "password": "Test-password-2034!"}
        response = self.client.post(reverse("login"), correct)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "thử quá nhiều lần")
        CustomerLoginAttempt.objects.update(window_start=timezone.now() - timedelta(minutes=16))
        self.assertRedirects(
            self.client.post(reverse("login"), correct),
            reverse("dashboard"),
            fetch_redirect_response=False,
        )


class StartupRegressionTests(SimpleTestCase):
    def startup_module(self):
        spec = spec_from_file_location(
            "audit_start_server", settings.BASE_DIR / "tools/start_server.py"
        )
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_AU12_starting_an_existing_server_preserves_its_pid(self):
        module = self.startup_module()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            (base / ".runtime").mkdir()
            pid = base / ".runtime/web.pid"
            pid.write_text("4242")
            with patch.object(module, "database_ready", return_value=True), patch.object(
                module, "web_ready", return_value=True
            ), patch.object(module.subprocess, "Popen") as spawn:
                module.start_server(base)
            spawn.assert_not_called()
            self.assertEqual(pid.read_text(), "4242")

    def test_AU13_failed_worker_does_not_overwrite_the_existing_pid_file(self):
        module = self.startup_module()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            (base / ".runtime").mkdir()
            pid = base / ".runtime/web.pid"
            pid.write_text("4242")
            process = Mock(pid=9999)
            process.poll.return_value = 1
            with patch.object(module, "database_ready", return_value=True), patch.object(
                module, "web_ready", return_value=False
            ), patch.object(module.subprocess, "Popen", return_value=process):
                with self.assertRaises(SystemExit):
                    module.start_server(base)
            self.assertEqual(pid.read_text(), "4242")
