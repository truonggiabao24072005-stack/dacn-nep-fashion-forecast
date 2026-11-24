from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from store.forecast.replenishment import create_suggestion, suggestion_preview, suggestion_stale
from store.models import (
    ForecastUnit,
    Product,
    ReplenishmentPolicy,
    ReplenishmentSuggestion,
    Variant,
)
from store.services.catalog import set_safety_stock
from store.tests import test_business as fixture_module


class ReplenishmentDeepReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = (
            fixture_module.fixture()
        )

    opening = fixture_module.BusinessTests.opening
    sale = fixture_module.BusinessTests.sale
    post_sale = fixture_module.BusinessTests.post_sale

    def value(self):
        value = fixture_module.BusinessTests.forecast_value(self)
        value.refresh_from_db()
        return value

    def test_stale_policy_form_cannot_overwrite_newer_policy(self):
        old = set_safety_stock(self.admin, self.product.pk, 5)
        self.client.force_login(self.admin)
        self.client.get(reverse("safety", args=[self.product.pk]))
        current = set_safety_stock(self.admin, self.product.pk, 15)
        r = self.client.post(
            reverse("safety", args=[self.product.pk]), {"quantity": 2, "policy_id": old.pk}
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Tồn an toàn đã thay đổi")
        self.assertEqual(
            ReplenishmentPolicy.objects.get(product=self.product, effective_to__isnull=True).pk,
            current.pk,
        )

    def test_first_policy_form_detects_another_admin_created_policy(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("safety", args=[self.product.pk]))
        current = set_safety_stock(self.admin, self.product.pk, 15)
        r = self.client.post(
            reverse("safety", args=[self.product.pk]), {"quantity": 2, "policy_id": 0}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            ReplenishmentPolicy.objects.get(product=self.product, effective_to__isnull=True).pk,
            current.pk,
        )

    def test_latest_ten_suggestions_are_shown_newest_first(self):
        self.opening()
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.value()
        saved = [create_suggestion(self.admin, value.pk) for _ in range(12)]
        self.client.force_login(self.admin)
        r = self.client.get(reverse("forecast_detail", args=[value.pk]))
        self.assertEqual(
            [x["object"].pk for x in r.context["suggestions"]],
            [x.pk for x in reversed(saved[-10:])],
        )

    def test_mapping_to_another_product_invalidates_saved_suggestion(self):
        self.opening()
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.value()
        saved = create_suggestion(self.admin, value.pk)
        other = Product.objects.create(
            code="OTHER",
            name="Sản phẩm khác",
            category=self.product.category,
            brand=self.product.brand,
            unit=self.product.unit,
        )
        Variant.objects.create(
            sku="OTHER-M", product=other, size=self.v.size, color=self.v.color, selling_price=100000
        )
        set_safety_stock(self.admin, other.pk, 5)
        ForecastUnit.objects.filter(pk=value.forecast_unit_id).update(internal_product=other)
        self.assertTrue(suggestion_stale(ReplenishmentSuggestion.objects.get(pk=saved.pk)))

    def test_direct_policy_quantity_change_invalidates_snapshot(self):
        self.opening()
        policy = set_safety_stock(self.admin, self.product.pk, 5)
        value = self.value()
        saved = create_suggestion(self.admin, value.pk)
        ReplenishmentPolicy.objects.filter(pk=policy.pk).update(safety_stock_qty=20)
        self.assertTrue(suggestion_stale(ReplenishmentSuggestion.objects.get(pk=saved.pk)))

    def test_dashboard_and_low_filter_exclude_unsellable_variants(self):
        self.client.force_login(self.admin)
        for obj, field, bad, good in [
            (self.product, "is_active", False, True),
            (self.product.category, "is_active", False, True),
            (self.product.brand, "is_active", False, True),
            (self.v.size, "is_active", False, True),
            (self.v.color, "is_active", False, True),
            (self.v, "selling_price", Decimal(0), Decimal(100000)),
        ]:
            with self.subTest(model=type(obj).__name__, field=field):
                type(obj).objects.filter(pk=obj.pk).update(**{field: bad})
                try:
                    self.assertEqual(self.client.get(reverse("dashboard")).context["low_count"], 0)
                    rows = self.client.get(reverse("inventory"), {"mode": "low"}).context["page"]
                    self.assertNotIn(self.v.pk, [row.variant_id for row in rows])
                finally:
                    type(obj).objects.filter(pk=obj.pk).update(**{field: good})

    def test_inventory_distinguishes_physical_stock_from_sellable_stock(self):
        self.opening([(self.v, 10)])
        Variant.objects.filter(pk=self.v.pk).update(is_active=False)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("inventory"), {"q": self.v.sku, "mode": "all"})
        self.assertContains(r, "Tồn hiện tại")
        self.assertContains(r, "Không đủ điều kiện bán")
        self.assertNotIn(self.v.pk, r.context["sellable_variant_ids"])

    def test_over_limit_preview_has_no_save_button(self):
        set_safety_stock(self.admin, self.product.pk, 2147483647)
        value = self.value()
        self.client.force_login(self.admin)
        r = self.client.get(reverse("forecast_detail", args=[value.pk]))
        self.assertContains(r, "vượt giới hạn")
        self.assertNotContains(r, "Tính lại và lưu đề xuất")
        self.assertEqual(ReplenishmentSuggestion.objects.count(), 0)

    def test_current_policy_form_saves_and_missing_version_does_not(self):
        old = set_safety_stock(self.admin, self.product.pk, 5)
        self.client.force_login(self.admin)
        url = reverse("safety", args=[self.product.pk])
        self.assertEqual(
            self.client.post(url, {"quantity": 9, "policy_id": old.pk}).status_code, 302
        )
        self.assertEqual(self.client.post(url, {"quantity": 1}).status_code, 200)
        self.assertEqual(
            ReplenishmentPolicy.objects.get(
                product=self.product, effective_to__isnull=True
            ).safety_stock_qty,
            9,
        )

    def test_stock_change_between_preview_and_save_is_recalculated(self):
        self.opening([(self.v, 20)])
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.value()
        preview = suggestion_preview(value)
        self.post_sale(self.sale(6))
        saved = create_suggestion(self.admin, value.pk)
        self.assertEqual((preview["stock"], saved.inventory_qty_snapshot), (20, 14))
        self.assertEqual(saved.inventory_versions["period_sales_qty"], 6)
        self.assertEqual(saved.suggested_qty, 18)

    def test_rounding_and_zero_boundaries(self):
        self.opening([(self.v, 20)])
        set_safety_stock(self.admin, self.product.pk, 5)
        for forecast, expected in [
            ("32.0000", 17),
            ("32.0001", 18),
            ("15", 0),
            ("15.0001", 1),
            ("0", 0),
        ]:
            with self.subTest(forecast=forecast):
                value = fixture_module.BusinessTests.forecast_value(self, forecast=forecast)
                value.refresh_from_db()
                self.assertEqual(suggestion_preview(value)["quantity"], expected)
                self.assertEqual(create_suggestion(self.admin, value.pk).suggested_qty, expected)

    def test_month_boundary_uses_vietnam_local_time(self):
        start = timezone.make_aware(datetime.combine(timezone.localdate().replace(day=1), time.min))
        with patch("store.services.documents.timezone.now", return_value=start - timedelta(days=2)):
            self.opening([(self.v, 30)])
        with patch(
            "store.services.documents.timezone.now", return_value=start - timedelta(seconds=1)
        ):
            self.post_sale(self.sale(3))
        with patch("store.services.documents.timezone.now", return_value=start):
            self.post_sale(self.sale(2))
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.value()
        saved = create_suggestion(self.admin, value.pk)
        self.assertEqual(saved.inventory_versions["period_sales_qty"], 2)
        self.assertEqual(saved.inventory_qty_snapshot, 25)
        self.assertEqual(saved.suggested_qty, 11)

    def test_audit_failure_rolls_back_suggestion(self):
        self.opening()
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.value()
        with patch(
            "store.forecast.replenishment.audit", side_effect=RuntimeError("test audit failure")
        ):
            with self.assertRaises(RuntimeError):
                create_suggestion(self.admin, value.pk)
        self.assertEqual(ReplenishmentSuggestion.objects.count(), 0)

    def test_staff_cannot_change_policy_or_save_suggestion(self):
        policy = set_safety_stock(self.admin, self.product.pk, 5)
        value = self.value()
        for actor in [self.sales, self.kho]:
            self.client.force_login(actor)
            self.assertEqual(
                self.client.post(
                    reverse("safety", args=[self.product.pk]),
                    {"quantity": 9, "policy_id": policy.pk},
                ).status_code,
                403,
            )
            self.assertEqual(self.client.post(reverse("suggest", args=[value.pk])).status_code, 403)
        self.assertEqual(ReplenishmentSuggestion.objects.count(), 0)
