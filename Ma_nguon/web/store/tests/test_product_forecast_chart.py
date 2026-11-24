from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from store.forecast.charts import comparison_rows, comparison_svg
from store.models import ForecastRun, ForecastValue, ModelResult
from store.tests.test_research_workspace import research_fixture


class ComparisonChartTests(SimpleTestCase):
    def test_missing_values_are_gaps_and_signed_errors_have_zero_baseline(self):
        rows = [
            {
                "month": date(2023, 7, 1),
                "actual": Decimal("25"),
                "forecast": Decimal("14.4406"),
                "difference": Decimal("-10.5594"),
            },
            {
                "month": date(2023, 8, 1),
                "actual": None,
                "forecast": Decimal("14.89"),
                "difference": None,
            },
        ]
        svg = comparison_svg(rows)
        self.assertIn("-10.56", svg)
        self.assertIn("Chưa đủ dữ liệu", svg)
        self.assertIn("Dự đoán − Thực tế", svg)
        self.assertNotIn("nan", svg.lower())


class ProductForecastTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, _, cls.warehouse, cls.ds = research_fixture()

    def test_only_selected_model_and_target_period_are_compared(self):
        unit = self.ds.forecast_units.get(external_key="SKU-0")
        model = ModelResult.objects.get(method="naive")
        run = ForecastRun.objects.create(
            model_result=model,
            cutoff_month=date(2023, 6, 1),
            target_month=date(2023, 7, 1),
            status="SUCCEEDED",
            scope_key="ALL_SOURCE_SITES_CHANNELS",
        )
        ForecastValue.objects.create(
            run=run, forecast_unit=unit, result_status="VALID", raw_value=2, nonnegative_value=2
        )
        rows = comparison_rows(unit, model, date(2023, 8, 1))
        july = next(row for row in rows if row["month"] == date(2023, 7, 1))
        self.assertEqual(july["difference"], 2 - july["actual"])
        self.assertIsNone(rows[-1]["actual"])
        self.assertIsNone(rows[-1]["difference"])
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("research_workspace"),
            {"dataset": self.ds.pk, "target": "2023-08", "unit": unit.pk},
        )
        self.assertContains(response, "Dự đoán so với thực tế")
        for unwanted in [
            "Validation MAE",
            "WAPE",
            "MAPE",
            "Tình huống nhập hàng",
            "Chạy lại bốn phương pháp",
        ]:
            self.assertNotContains(response, unwanted)
        self.assertContains(response, 'type="hidden" name="experiment"')
