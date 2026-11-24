from decimal import Decimal
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from store.forms.checkout import CheckoutForm
from store.models import (
    SalePayment,
    StockBalance,
    StockEntry,
    WebGuestOwner,
    WebOrder,
    WebOrderLine,
)
from store.services.documents import BusinessError, confirm_document
from store.services.orders import accept_order, fingerprint, submit_order
from store.services.payment_preferences import normalise_payment_method
from store.tests.test_business import fixture
from store.tests.test_shop import stock


class PaymentPreferenceUnitTests(SimpleTestCase):
    def test_two_supported_choices_keep_their_codes(self):
        self.assertEqual(normalise_payment_method("CASH"), "CASH")
        self.assertEqual(normalise_payment_method("TRANSFER"), "TRANSFER")

    def test_unknown_and_blank_methods_are_rejected(self):
        for method in ["CARD", "", None, "transfer"]:
            with self.subTest(method=method), self.assertRaises(ValueError):
                normalise_payment_method(method)

    def test_request_fingerprint_includes_the_chosen_method(self):
        data = {"customer_name": "Khách thử", "phone": "0900000000", "payment_method": "CASH"}
        before = fingerprint("owner", [[1, 1, "100000"]], data)
        data["payment_method"] = "TRANSFER"
        self.assertNotEqual(before, fingerprint("owner", [[1, 1, "100000"]], data))

    def test_checkout_presents_and_requires_payment_choice(self):
        field = CheckoutForm().fields["payment_method"]
        self.assertTrue(field.required)
        self.assertEqual(dict(field.choices)["TRANSFER"], "Chuyển khoản tại quầy")
        self.assertIn('type="radio"', str(CheckoutForm()["payment_method"]))


class TransferStockIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, _, _, cls.v, _, _ = fixture()
        stock(cls.admin, cls.v, 10)

    def contact(self, method="TRANSFER"):
        return {
            "customer_name": "Khách thử chuyển khoản",
            "phone": "0900000000",
            "payment_method": method,
        }

    def place(self, method="TRANSFER", key=None):
        return submit_order(
            "p" * 64, key or uuid4(), [[self.v.pk, 2, "100000"]], self.contact(method)
        )[0]

    def test_choice_is_stored_without_payment_or_stock_deduction(self):
        order = self.place()
        order.refresh_from_db()
        self.assertEqual(order.payment_preference, "TRANSFER")
        self.assertFalse(SalePayment.objects.exists())
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)

    def test_same_request_key_with_changed_method_is_rejected(self):
        key = uuid4()
        order = self.place("CASH", key)
        with self.assertRaises(BusinessError):
            self.place("TRANSFER", key)
        self.assertEqual(WebOrder.objects.count(), 1)
        order.refresh_from_db()
        self.assertEqual(order.payment_preference, "CASH")

    def test_staff_receives_the_choice_but_acceptance_does_not_take_stock(self):
        order = accept_order(self.sales, self.place().pk, 1)
        self.client.force_login(self.sales)
        response = self.client.get(reverse("document", args=["sale", order.sale_id]))
        self.assertEqual(response.context["confirm_form"]["method"].value(), "TRANSFER")
        self.assertContains(response, "Đã đối chiếu tiền nhận với tổng đơn")
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)

    def test_unacknowledged_transfer_rolls_back_payment_and_stock(self):
        order = accept_order(self.sales, self.place().pk, 1)
        sale = order.sale
        with self.assertRaises(BusinessError):
            confirm_document(
                self.sales,
                "sale",
                sale.pk,
                sale.version,
                uuid4(),
                {"method": "TRANSFER", "transfer_ack": False},
            )
        self.assertFalse(SalePayment.objects.exists())
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 10)

    def test_confirmed_transfer_posts_payment_and_stock_exactly_once(self):
        order = accept_order(self.sales, self.place().pk, 1)
        sale = order.sale
        key = uuid4()
        payment = {"method": "TRANSFER", "transfer_ack": True, "reference": "THU-CHUYEN-KHOAN-001"}
        confirm_document(self.sales, "sale", sale.pk, sale.version, key, payment)
        entries = StockEntry.objects.count()
        confirm_document(self.sales, "sale", sale.pk, sale.version, key, payment)
        self.assertEqual(
            SalePayment.objects.filter(
                sale=sale, method="TRANSFER", amount=Decimal("200000")
            ).count(),
            1,
        )
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 8)
        self.assertEqual(StockEntry.objects.count(), entries)
        order.refresh_from_db()
        self.assertEqual(order.lifecycle_status, "COMPLETED")

    def test_sql_rejects_unknown_payment_choice(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            WebOrder.objects.create(
                code="BAD-PREF",
                request_key=uuid4(),
                owner_hash="s" * 64,
                payload_hash="b" * 64,
                customer_name="Khách thử",
                phone="0900000000",
                total_amount=100000,
                payment_preference="CARD",
            )

    def test_sql_preserves_the_choice_already_submitted(self):
        order = self.place()
        with self.assertRaises(IntegrityError), transaction.atomic():
            WebOrder.objects.filter(pk=order.pk).update(payment_preference="CASH")

    def test_legacy_request_can_be_retried_without_rewriting_its_snapshot(self):
        data = {"customer_name": "Khách cũ", "phone": "0900000000"}
        quote = [[self.v.pk, 1, "100000"]]
        key = uuid4()
        owner = "l" * 64
        order = WebOrder.objects.create(
            code="LEGACY-PREF",
            request_key=key,
            owner_hash=owner,
            payload_hash=fingerprint(owner, quote, data, legacy=True),
            customer_name=data["customer_name"],
            phone=data["phone"],
            total_amount=100000,
        )
        WebOrderLine.objects.create(
            order=order,
            variant=self.v,
            quantity=1,
            unit_price=100000,
            name_snapshot="Sản phẩm thử",
            sku_snapshot=self.v.sku,
            variant_snapshot="Cỡ thử",
        )
        again, created = submit_order(owner, key, quote, data)
        self.assertFalse(created)
        self.assertEqual(again.pk, order.pk)
        self.assertEqual(again.payment_preference, "UNSPECIFIED")
