from django.test import TestCase
from django.urls import reverse

from store.forecast.replenishment import create_suggestion, suggestion_preview, suggestion_stale
from store.models import ReplenishmentSuggestion, Variant
from store.services.catalog import set_safety_stock
from store.tests import test_business as business_fixture


class ManagementReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = (
            business_fixture.fixture()
        )

    opening = business_fixture.BusinessTests.opening
    sale = business_fixture.BusinessTests.sale
    post_sale = business_fixture.BusinessTests.post_sale

    def forecast_value(self, *args, **kwargs):
        value = business_fixture.BusinessTests.forecast_value(self, *args, **kwargs)
        value.refresh_from_db()
        return value

    def test_preview_matches_saved_amount_after_sale_and_excludes_inactive_stock(self):
        self.opening([(self.v, 20), (self.v2, 100)])
        Variant.objects.filter(pk=self.v2.pk).update(is_active=False)
        set_safety_stock(self.admin, self.product.pk, 5)
        self.post_sale(self.sale(3))
        value = self.forecast_value()
        preview = suggestion_preview(value)
        self.assertEqual((preview["sold"], preview["stock"], preview["quantity"]), (3, 17, 18))
        self.assertEqual(ReplenishmentSuggestion.objects.count(), 0)
        saved = create_suggestion(self.admin, value.pk)
        self.assertEqual(saved.suggested_qty, preview["quantity"])

    def test_research_does_not_show_preview_or_save_button(self):
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.forecast_value("RESEARCH")
        self.client.force_login(self.admin)
        r = self.client.get(reverse("forecast_detail", args=[value.pk]))
        self.assertContains(r, "Chưa tính lượng nhập")
        self.assertNotContains(r, "Số liệu để đối chiếu trước khi lưu")
        self.assertNotContains(r, "Tính lại và lưu đề xuất")

    def test_zero_amount_is_explained_and_get_never_saves(self):
        self.opening([(self.v, 50)])
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.forecast_value()
        self.client.force_login(self.admin)
        r = self.client.get(reverse("forecast_detail", args=[value.pk]))
        self.assertContains(r, "Lượng nhập tham khảo là 0")
        self.assertEqual(ReplenishmentSuggestion.objects.count(), 0)

    def test_warehouse_can_read_preview_but_cannot_save(self):
        self.opening()
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.forecast_value()
        self.client.force_login(self.kho)
        r = self.client.get(reverse("forecast_detail", args=[value.pk]))
        self.assertContains(r, "Số liệu để đối chiếu trước khi lưu")
        self.assertNotContains(r, "Tính lại và lưu đề xuất")
        self.assertEqual(self.client.post(reverse("suggest", args=[value.pk])).status_code, 403)

    def test_saved_suggestion_becomes_stale_and_recalculation_uses_new_policy(self):
        self.opening()
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.forecast_value()
        saved = create_suggestion(self.admin, value.pk)
        set_safety_stock(self.admin, self.product.pk, 15)
        self.assertTrue(suggestion_stale(saved))
        self.assertEqual(suggestion_preview(value)["quantity"], 38)
        self.assertEqual(create_suggestion(self.admin, value.pk).suggested_qty, 38)

    def test_dataset_without_completed_run_has_clear_empty_state(self):
        value = self.forecast_value()
        value.run.status = "PENDING"
        value.run.save()
        self.client.force_login(self.admin)
        r = self.client.get(
            reverse("forecasts"), {"dataset": value.forecast_unit.dataset_version_id}
        )
        self.assertContains(r, "Chưa có lần dự báo hoàn tất")
        self.assertNotContains(r, "Phạm vi có thể dự báo")
