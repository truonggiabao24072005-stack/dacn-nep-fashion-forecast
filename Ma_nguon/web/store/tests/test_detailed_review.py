from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from store.forecast.replenishment import create_suggestion, suggestion_reasons
from store.forms.documents import DocumentLineForm
from store.models import Product, ReplenishmentSuggestion, Role, StockBalance, User, Variant
from store.services.catalog import save_catalog, set_safety_stock
from store.services.documents import BusinessError, confirm_document, create_document, set_line
from store.services.reports import reconciliation
from store.tests import test_business as business


class StorefrontDetailedReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = business.fixture()

    def test_filtered_price_sort_matches_the_prices_shown_on_cards(self):
        other = Product.objects.create(
            code="OTHER",
            name="Mẫu khác",
            category=self.product.category,
            brand=self.product.brand,
            unit="chiếc",
        )
        Variant.objects.create(
            product=other,
            size=self.v2.size,
            color=self.v2.color,
            sku="OTHER-M-TRANG",
            selling_price=110000,
        )
        # The first product starts at 100,000, while its white variant costs 120,000.
        for sort, descending in [("price_asc", False), ("price_desc", True)]:
            with self.subTest(sort=sort):
                response = self.client.get(
                    reverse("shop_catalogue"),
                    {
                        "color": self.v2.color.code,
                        "sort": sort,
                    },
                )
                prices = [item["price"] for item in response.context["items"]]
                self.assertEqual(len(prices), 2)
                self.assertEqual(prices, sorted(prices, reverse=descending))

    def test_variant_price_payload_keeps_all_integer_digits(self):
        amount = Decimal("999999999999999999")
        Variant.objects.filter(pk=self.v.pk).update(selling_price=amount)
        response = self.client.get(reverse("shop_product", args=[self.product.pk]))
        value = next(
            row["price"] for row in response.context["variant_data"] if row["id"] == self.v.pk
        )
        self.assertIsInstance(value, str)
        self.assertEqual(value, str(amount))

    def test_physical_count_can_correct_stock_after_variant_and_category_stop_selling(self):
        business.BusinessTests.opening(self)
        Variant.objects.filter(pk=self.v.pk).update(is_active=False)
        type(self.product.category).objects.filter(pk=self.product.category_id).update(
            is_active=False
        )
        form = DocumentLineForm(
            {"version": 1, "variant": self.v.pk, "quantity": 7}, kind="adjustment"
        )
        self.assertTrue(form.is_valid(), form.errors)
        doc = create_document(
            self.admin, "adjustment", {"kind": "COUNT", "reason": "Kiểm đếm thực tế"}
        )
        doc = set_line(self.admin, "adjustment", doc.pk, doc.version, self.v, 7)
        confirm_document(self.admin, "adjustment", doc.pk, doc.version, uuid4())
        self.assertEqual(StockBalance.objects.get(variant=self.v).quantity, 7)
        self.assertFalse(reconciliation(self.admin).exists())


class ReplenishmentMetadataRaceTests(TransactionTestCase):
    def setUp(self):
        self.admin, _, _, self.product, self.v, _, _ = business.fixture()
        self.other_admin = User.objects.create_user("otheradmin", role=Role.ADMIN)
        set_safety_stock(self.admin, self.product.pk, 5)
        self.value = business.BusinessTests.forecast_value(self)

    def test_unit_changed_after_first_check_is_revalidated_before_suggestion_is_saved(self):
        checked, changed = Event(), Event()
        original = suggestion_reasons

        def pause_after_check(value):
            result = original(value)
            if not checked.is_set():
                checked.set()
                if not changed.wait(10):
                    raise RuntimeError("Timed out waiting for catalogue update")
            return result

        def save_suggestion():
            connections.close_all()
            try:
                actor = User.objects.get(pk=self.admin.pk)
                create_suggestion(actor, self.value.pk)
                return "saved"
            except BusinessError as error:
                return str(error)
            finally:
                connections.close_all()

        with patch(
            "store.forecast.replenishment.suggestion_reasons", side_effect=pause_after_check
        ):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(save_suggestion)
                try:
                    self.assertTrue(checked.wait(10))
                    product = Product.objects.get(pk=self.product.pk)
                    save_catalog(
                        self.other_admin,
                        "products",
                        {
                            "code": product.code,
                            "name": product.name,
                            "category": product.category,
                            "brand": product.brand,
                            "unit": "bộ",
                            "is_active": True,
                        },
                        product.pk,
                        product.version,
                    )
                finally:
                    changed.set()
                outcome = future.result(timeout=20)
        self.assertIn("Đơn vị", outcome)
        self.assertEqual(ReplenishmentSuggestion.objects.count(), 0)
