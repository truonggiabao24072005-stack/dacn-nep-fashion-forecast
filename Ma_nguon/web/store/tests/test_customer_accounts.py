from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from store.models import *
from store.services.catalog import save_user
from store.services.customers import account_owner, claim_guest_orders
from store.services.documents import BusinessError, authorize
from store.services.orders import cancel_order, submit_order
from store.tests.test_business import fixture
from store.tests.test_shop import stock

PASSWORD = "Customer-test-2042!"


def customer(username="ban_nep"):
    user = User.objects.create_user(
        username, password=PASSWORD, full_name="Bạn của Nếp", role=Role.CUSTOMER
    )
    CustomerProfile.objects.create(user=user, phone="0900000000")
    return user


class CustomerAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = fixture()
        stock(cls.admin, cls.v)
        cls.user = customer()
        cls.other = customer("ban_khac")

    def registration(self, **overrides):
        return {
            "username": "ban_moi",
            "full_name": "Bạn mới",
            "phone": "090 111 2222",
            "password1": PASSWORD,
            "password2": PASSWORD,
            **overrides,
        }

    def sign_in(self, c=None, **overrides):
        return (c or self.client).post(
            reverse("shop_login"),
            {"username": self.user.username, "password": PASSWORD, **overrides},
        )

    def prepare(self, c=None):
        c = c or self.client
        c.post(reverse("shop_cart_action"), {"variant_id": self.v.pk, "quantity": 1})
        form = c.get(reverse("shop_checkout")).context["form"]
        return {
            "customer_name": "Khách đặt hàng",
            "phone": "0900000000",
            "payment_method": "CASH",
            "note": "Dữ liệu kiểm thử",
            "request_key": str(form.initial["request_key"]),
            "quote": form.initial["quote"],
        }

    def place(self, c=None):
        c = c or self.client
        payload = self.prepare(c)
        r = c.post(reverse("shop_checkout"), payload)
        self.assertEqual(r.status_code, 302)
        return WebOrder.objects.get(request_key=payload["request_key"])

    def test_CA01_register_fixes_role_hashes_password_and_normalizes_username(self):
        self.client.post(
            reverse("shop_register"),
            self.registration(
                username="BAN_MOI", role=Role.ADMIN, is_staff=True, is_superuser=True
            ),
        )
        u = User.objects.get(username="ban_moi")
        self.assertEqual(u.role, Role.CUSTOMER)
        self.assertFalse(u.is_staff or u.is_superuser)
        self.assertNotEqual(u.password, PASSWORD)
        self.assertTrue(u.check_password(PASSWORD))
        self.assertEqual(u.customer_profile.phone, "0901112222")
        self.assertEqual(int(self.client.session["_auth_user_id"]), u.pk)
        self.assertEqual(AuditEvent.objects.filter(actor=u).count(), 0)

    def test_CA02_registration_validates_duplicate_password_phone_and_required_name(self):
        bad = [
            {"username": self.user.username.upper()},
            {"password1": "1234567890", "password2": "1234567890"},
            {"password2": "Mismatch-2042!"},
            {"phone": "hello"},
            {"full_name": "X"},
            {"username": "ab spaces"},
        ]
        for values in bad:
            response = self.client.post(reverse("shop_register"), self.registration(**values))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="ban_moi").exists())

    def test_CA03_registration_race_returns_form_error_without_partial_account(self):
        with patch(
            "store.views.customers.User.objects.create_user", side_effect=IntegrityError("unique")
        ):
            response = self.client.post(reverse("shop_register"), self.registration())
        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="ban_moi").exists())

    def test_CA04_login_preserves_cart_rotates_session_and_invalidates_old_checkout(self):
        payload = self.prepare()
        before = self.client.session.session_key
        response = self.sign_in(username="  BAN_NEP  ", next=reverse("shop_checkout"))
        self.assertRedirects(response, reverse("shop_checkout"), fetch_redirect_response=False)
        self.assertNotEqual(self.client.session.session_key, before)
        self.assertEqual(self.client.session["nep_cart"], {str(self.v.pk): 1})
        self.assertNotIn("nep_checkout_keys", self.client.session)
        response = self.client.post(reverse("shop_checkout"), payload)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertEqual(WebOrder.objects.count(), 0)

    def test_CA05_login_rejects_wrong_inactive_and_employee_accounts(self):
        for username, password in [
            (self.user.username, "incorrect"),
            (self.sales.username, "Test-password-2034!"),
            ("absent", PASSWORD),
        ]:
            response = self.sign_in(username=username, password=password)
            self.assertContains(response, "Tên đăng nhập hoặc mật khẩu chưa đúng.")
            self.assertNotIn("_auth_user_id", self.client.session)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertContains(self.sign_in(), "Tên đăng nhập hoặc mật khẩu chưa đúng.")

    def test_CA06_throttle_is_persistent_and_expires_after_window(self):
        for _ in range(8):
            self.sign_in(password="incorrect")
        self.assertContains(self.sign_in(), "thử quá nhiều lần")
        self.assertNotIn("_auth_user_id", self.client.session)
        CustomerLoginAttempt.objects.update(window_start=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.sign_in().status_code, 302)

    def test_CA07_next_cannot_redirect_to_other_host(self):
        for value in ["https://evil.example/", "//evil.example/", "/\\evil.example/"]:
            c = Client()
            self.assertRedirects(
                self.sign_in(c, next=value), reverse("shop_account"), fetch_redirect_response=False
            )

    def test_CA08_guests_own_orders_only_claim_current_session_not_same_phone(self):
        mine = self.place()
        other = self.place(Client())
        balances = list(StockBalance.objects.values_list("variant_id", "quantity", "version"))
        counts = (Customer.objects.count(), SaleOrder.objects.count(), SalePayment.objects.count())
        self.sign_in()
        mine.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(mine.account_id, self.user.pk)
        self.assertIsNone(other.account_id)
        self.assertContains(self.client.get(reverse("shop_orders")), mine.code)
        self.assertNotContains(self.client.get(reverse("shop_orders")), other.code)
        self.assertEqual(
            balances, list(StockBalance.objects.values_list("variant_id", "quantity", "version"))
        )
        self.assertEqual(
            counts,
            (Customer.objects.count(), SaleOrder.objects.count(), SalePayment.objects.count()),
        )

    def test_CA09_registration_also_preserves_cart_and_claims_orders(self):
        order = self.place()
        self.prepare()
        self.client.post(reverse("shop_register"), self.registration())
        order.refresh_from_db()
        u = User.objects.get(username="ban_moi")
        self.assertEqual(order.account_id, u.pk)
        self.assertEqual(self.client.session["nep_cart"], {str(self.v.pk): 1})

    def test_CA10_account_orders_survive_new_session_and_other_customer_cannot_read_or_cancel(self):
        self.sign_in()
        order = self.place()
        self.assertEqual(order.account_id, self.user.pk)
        self.client.post(reverse("shop_logout"))
        c = Client()
        self.sign_in(c)
        self.assertEqual(c.get(reverse("shop_order", args=[order.pk])).status_code, 200)
        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.get(reverse("shop_order", args=[order.pk])).status_code, 404)
        self.assertEqual(
            other.post(reverse("shop_cancel", args=[order.pk]), {"version": 1}).status_code, 404
        )
        self.assertEqual(Client().get(reverse("shop_order", args=[order.pk])).status_code, 404)
        c.post(reverse("shop_cancel", args=[order.pk]), {"version": 1})
        order.refresh_from_db()
        self.assertEqual(order.status, "CANCELLED")

    def test_CA11_old_guest_cookie_and_service_cannot_access_claimed_order(self):
        order = self.place()
        old_key = self.client.session.session_key
        self.sign_in()
        stale = Client()
        stale.cookies["sessionid"] = old_key
        self.assertEqual(stale.get(reverse("shop_order", args=[order.pk])).status_code, 404)
        self.assertEqual(
            stale.post(reverse("shop_cancel", args=[order.pk]), {"version": 1}).status_code, 404
        )
        with self.assertRaises(BusinessError):
            cancel_order(order.pk, 1, owner=order.owner_hash)
        with self.assertRaises(BusinessError):
            submit_order(
                order.owner_hash,
                uuid4(),
                [[self.v.pk, 1, "100000"]],
                {"customer_name": "Test", "phone": "0900000000"},
            )
        with self.assertRaises(BusinessError):
            claim_guest_orders(order.owner_hash, self.other)

    def test_CA12_profile_prefills_checkout_and_preserves_order_contact_snapshot(self):
        self.sign_in()
        order = self.place()
        self.client.post(
            reverse("shop_account"),
            {"full_name": "Tên mới", "phone": "0911222333", "role": Role.ADMIN},
        )
        self.prepare()
        form = self.client.get(reverse("shop_checkout")).context["form"]
        self.assertEqual(form.initial["customer_name"], "Tên mới")
        self.assertEqual(form.initial["phone"], "0911222333")
        order.refresh_from_db()
        self.assertEqual(order.customer_name, "Khách đặt hàng")
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, Role.CUSTOMER)

    def test_CA13_customer_cannot_enter_internal_routes_or_call_staff_services(self):
        self.client.force_login(self.user)
        for path in [
            "/quan-tri/",
            "/ton-kho/",
            "/bao-cao/",
            "/du-bao/",
            "/nhan-vien/",
            "/nhat-ky/",
            "/huong-dan/",
            "/doi-mat-khau/",
            "/quan-tri/don-tren-web/",
            "/danh-muc/products/",
        ]:
            self.assertEqual(self.client.get(path).status_code, 403, path)
        with self.assertRaises(PermissionDenied):
            authorize(self.user, Role.values)
        self.assertRedirects(
            self.client.get(reverse("login")),
            reverse("shop_account"),
            fetch_redirect_response=False,
        )

    def test_CA14_employee_login_and_editor_are_separate_from_customers(self):
        r = self.client.post(
            reverse("login"), {"username": self.user.username, "password": PASSWORD}
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("employees")), self.user.username)
        self.assertEqual(
            self.client.get(reverse("employee_edit", args=[self.user.pk])).status_code, 404
        )
        values = {
            "username": "staffnew",
            "full_name": "Test",
            "role": Role.CUSTOMER,
            "is_active": True,
            "new_password": PASSWORD,
        }
        with self.assertRaises(BusinessError):
            save_user(self.admin, values)
        values["role"] = Role.ADMIN
        with self.assertRaises(BusinessError):
            save_user(self.admin, values, pk=self.user.pk, version=1)
        self.assertRedirects(
            self.client.get(reverse("shop_login")),
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_CA15_database_rejects_customer_staff_flags(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.user.pk).update(is_staff=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.user.pk).update(is_superuser=True)

    def test_CA16_logout_is_post_only_and_flushes_cart_and_auth(self):
        self.sign_in()
        self.prepare()
        self.assertEqual(self.client.get(reverse("shop_logout")).status_code, 405)
        self.client.post(reverse("shop_logout"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("nep_cart", self.client.session)
        self.assertEqual(self.client.get(reverse("shop_account")).status_code, 302)

    def test_CA17_auth_forms_and_logout_require_csrf_and_are_not_cached(self):
        c = Client(enforce_csrf_checks=True)
        for name in ["shop_login", "shop_register", "shop_password", "shop_account"]:
            if name in ["shop_password", "shop_account"]:
                c.force_login(self.user)
            response = c.get(reverse(name))
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(c.post(reverse(name), {}).status_code, 403)
        self.assertEqual(c.post(reverse("shop_logout")).status_code, 403)

    def test_CA18_password_change_checks_old_password_keeps_this_session_invalidates_other(self):
        self.sign_in()
        other = Client()
        self.sign_in(other)
        before = self.client.session.session_key
        payload = {
            "old_password": "incorrect",
            "new_password1": "New-customer-2043!",
            "new_password2": "New-customer-2043!",
        }
        self.assertEqual(self.client.post(reverse("shop_password"), payload).status_code, 200)
        payload["old_password"] = PASSWORD
        too_long = {
            **payload,
            "new_password1": "Xy!" + ("a" * 126),
            "new_password2": "Xy!" + ("a" * 126),
        }
        self.assertIn(
            "new_password1",
            self.client.post(reverse("shop_password"), too_long).context["form"].errors,
        )
        self.assertRedirects(
            self.client.post(reverse("shop_password"), payload),
            reverse("shop_account"),
            fetch_redirect_response=False,
        )
        self.assertNotEqual(before, self.client.session.session_key)
        self.assertEqual(self.client.get(reverse("shop_account")).status_code, 200)
        self.assertEqual(other.get(reverse("shop_account")).status_code, 302)
        c = Client()
        self.assertEqual(self.sign_in(c).status_code, 200)
        self.assertEqual(self.sign_in(c, password="New-customer-2043!").status_code, 302)

    def test_CA19_account_submission_is_idempotent_and_requires_matching_owner(self):
        payload = {"customer_name": "Test", "phone": "0900000000"}
        quote = [[self.v.pk, 1, "100000"]]
        key = uuid4()
        one, created = submit_order(
            account_owner(self.user), key, quote, payload, account=self.user
        )
        same, created_again = submit_order(
            account_owner(self.user), key, quote, payload, account=self.user
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(one.pk, same.pk)
        with self.assertRaises(BusinessError):
            submit_order(account_owner(self.user), uuid4(), quote, payload, account=self.other)


class CustomerClaimConcurrencyTests(TransactionTestCase):
    def test_CA20_guest_checkout_racing_login_cannot_leave_an_unclaimed_order(self):
        admin, _, _, _, v, _, _ = fixture()
        stock(admin, v)
        u = customer()
        barrier = Barrier(2)
        owner = "a" * 64

        def worker(action):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                if action == "claim":
                    claim_guest_orders(owner, u)
                    return "claimed"
                try:
                    submit_order(
                        owner,
                        uuid4(),
                        [[v.pk, 1, "100000"]],
                        {"customer_name": "Guest", "phone": "0900000000"},
                    )
                    return "submitted"
                except BusinessError:
                    return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, ["claim", "submit"]))
        self.assertIn("claimed", results)
        self.assertFalse(WebOrder.objects.filter(owner_hash=owner, account__isnull=True).exists())
        self.assertEqual(WebGuestOwner.objects.get(pk=owner).account_id, u.pk)
