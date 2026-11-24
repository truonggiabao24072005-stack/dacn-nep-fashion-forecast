import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from store.forecast.replenishment import (
    create_suggestion,
    evaluate_matrix,
    import_research,
    month_add,
    suggestion_stale,
)
from store.models import *
from store.services.catalog import set_safety_stock
from store.services.documents import BusinessError
from store.tests import test_business as business_fixture
from store.tests import test_forecast as forecast_fixture


class ForecastAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = (
            business_fixture.fixture()
        )

    opening = business_fixture.BusinessTests.opening
    sale = business_fixture.BusinessTests.sale
    post_sale = business_fixture.BusinessTests.post_sale
    forecast_value = business_fixture.BusinessTests.forecast_value
    miniature_research = forecast_fixture.ForecastTests.miniature_research

    def modify_csv(self, root, name, **changes):
        path = root / name
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            fields = reader.fieldnames
            rows = list(reader)
        for row in rows:
            row.update(changes)
        with path.open("w", encoding="utf-8-sig", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_FA01_wrong_forecast_cutoff_rejected(self):
        with TemporaryDirectory() as directory, override_settings(
            RESEARCH_RESULTS_DIR=Path(directory)
        ):
            root = Path(directory)
            self.miniature_research(root)
            self.modify_csv(root, "du_bao_nghien_cuu_2023_08.csv", cutoff_month="2023-06")
            with self.assertRaises(BusinessError):
                import_research(self.admin)
            self.assertEqual(DatasetVersion.objects.count(), 0)

    def test_FA02_selection_tampering_rejected(self):
        with TemporaryDirectory() as directory, override_settings(
            RESEARCH_RESULTS_DIR=Path(directory)
        ):
            root = Path(directory)
            self.miniature_research(root)
            path = root / "lua_chon_truoc_kiem_tra.json"
            value = json.loads(path.read_text())
            value["winner"] = "linear"
            path.write_text(json.dumps(value))
            self.modify_csv(root, "du_bao_nghien_cuu_2023_08.csv", method="linear")
            with self.assertRaises(BusinessError):
                import_research(self.admin)

    def test_FA03_forecast_changes_make_a_distinct_dataset_version(self):
        with TemporaryDirectory() as directory, override_settings(
            RESEARCH_RESULTS_DIR=Path(directory)
        ):
            root = Path(directory)
            self.miniature_research(root)
            old = import_research(self.admin)
            self.modify_csv(root, "du_bao_nghien_cuu_2023_08.csv", forecast="4")
            new = import_research(self.admin)
            self.assertNotEqual(old.pk, new.pk)
            self.assertEqual(new.forecast_units.get().forecasts.get().nonnegative_value, 4)
            self.assertEqual(old.forecast_units.get().forecasts.get().nonnegative_value, 3)

    def test_FA04_metrics_must_match_saved_prediction_rows(self):
        with TemporaryDirectory() as directory, override_settings(
            RESEARCH_RESULTS_DIR=Path(directory)
        ):
            root = Path(directory)
            self.miniature_research(root)
            path = root / "tong_hop_thuc_nghiem.json"
            value = json.loads(path.read_text())
            value["test_metrics"][0]["mae"] = 99
            path.write_text(json.dumps(value))
            with self.assertRaises(BusinessError):
                import_research(self.admin)

    def test_FA05_duplicate_forecast_rows_raise_a_business_error(self):
        with TemporaryDirectory() as directory, override_settings(
            RESEARCH_RESULTS_DIR=Path(directory)
        ):
            root = Path(directory)
            self.miniature_research(root)
            path = root / "du_bao_nghien_cuu_2023_08.csv"
            with path.open("a", encoding="utf-8-sig") as file:
                file.write("MH00001,000ABC,2023-07,2023-08,naive,3\n")
            with self.assertRaises(BusinessError):
                import_research(self.admin)
            self.assertEqual(DatasetVersion.objects.count(), 0)

    def test_FA06_pair_counts_are_read_from_metrics(self):
        with TemporaryDirectory() as directory, override_settings(
            RESEARCH_RESULTS_DIR=Path(directory)
        ):
            root = Path(directory)
            self.miniature_research(root)
            dataset = import_research(self.admin)
            for result in ModelResult.objects.filter(experiment__dataset_version=dataset):
                self.assertEqual(result.scored_pair_manifest["validation_n"], 1)
                self.assertEqual(result.scored_pair_manifest["test_n"], 1)

    def test_FA07_unsellable_variants_do_not_reduce_replenishment(self):
        self.opening([(self.v, 10), (self.v2, 100)])
        set_safety_stock(self.admin, self.product.pk, 5)
        Variant.objects.filter(pk=self.v2.pk).update(is_active=False)
        value = self.forecast_value()
        suggestion = create_suggestion(self.admin, value.pk)
        self.assertEqual(suggestion.inventory_qty_snapshot, 10)
        self.assertEqual(suggestion.suggested_qty, 28)

    def test_FA08_variant_availability_changes_invalidate_old_suggestions(self):
        self.opening([(self.v, 10), (self.v2, 10)])
        set_safety_stock(self.admin, self.product.pk, 5)
        suggestion = create_suggestion(self.admin, self.forecast_value().pk)
        self.assertFalse(suggestion_stale(suggestion))
        Variant.objects.filter(pk=self.v2.pk).update(is_active=False)
        self.assertTrue(suggestion_stale(suggestion))

    def test_FA09_out_of_range_suggestion_is_rejected_without_saving(self):
        set_safety_stock(self.admin, self.product.pk, 0)
        value = self.forecast_value(forecast="2147483648")
        with self.assertRaises(BusinessError):
            create_suggestion(self.admin, value.pk)
        self.assertEqual(ReplenishmentSuggestion.objects.count(), 0)

    def test_FA10_unsuccessful_experiment_cannot_create_suggestions(self):
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.forecast_value()
        Experiment.objects.filter(pk=value.run.model_result.experiment_id).update(status="FAILED")
        with self.assertRaises(BusinessError):
            create_suggestion(self.admin, value.pk)

    def test_FA11_verified_zero_is_distinguished_from_unknown_months(self):
        value = self.forecast_value()
        MonthlySales.objects.create(
            forecast_unit=value.forecast_unit,
            month=value.run.cutoff_month,
            positive_qty=0,
            negative_qty_abs=0,
            net_qty=0,
            target_qty=0,
            observation_status="VERIFIED_ZERO",
            source_row_count=0,
        )
        self.client.force_login(self.admin)
        self.assertContains(
            self.client.get(reverse("forecast_detail", args=[value.pk])), "Đã xác nhận không bán"
        )

    def test_FA12_history_chart_keeps_missing_calendar_months_as_unknown(self):
        value = self.forecast_value()
        ds = value.forecast_unit.dataset_version
        for month in [ds.coverage_start, month_add(ds.coverage_start, 2)]:
            MonthlySales.objects.create(
                forecast_unit=value.forecast_unit,
                month=month,
                positive_qty=2,
                negative_qty_abs=0,
                net_qty=2,
                target_qty=2,
                observation_status="OBSERVED",
                source_row_count=1,
            )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("forecast_detail", args=[value.pk]))
        chart = response.context["chart"]
        self.assertIn(month_add(ds.coverage_start, 1).strftime("%m/%Y"), chart["labels"])
        self.assertIsNone(chart["values"][1])

    def test_FA16_replenishment_uses_remaining_sales_for_the_current_month(self):
        self.opening([(self.v, 20)])
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.forecast_value()
        self.post_sale(self.sale(6))
        suggestion = create_suggestion(self.admin, value.pk)
        self.assertEqual(suggestion.suggested_qty, 18)
        self.assertEqual(suggestion.inventory_versions["period_sales_qty"], 6)
        self.assertEqual(StockBalance.objects.get(pk=self.v.pk).quantity, 14)

    def test_FA17_sales_above_the_monthly_forecast_do_not_create_negative_remaining_demand(self):
        self.opening([(self.v, 50)])
        set_safety_stock(self.admin, self.product.pk, 5)
        value = self.forecast_value(forecast="20")
        self.post_sale(self.sale(30))
        self.assertEqual(create_suggestion(self.admin, value.pk).suggested_qty, 0)


class ForecastMatrixAuditTests(SimpleTestCase):
    def months(self, n=19):
        return [month_add(date(2022, 1, 1), i) for i in range(n)]

    def test_FA13_invalid_matrix_shapes_are_business_errors(self):
        for matrix, months in [
            ([], []),
            (np.zeros((0, 19)), self.months()),
            ([1, 2, 3], self.months(3)),
        ]:
            with self.subTest(shape=np.shape(matrix)), self.assertRaises(BusinessError):
                evaluate_matrix(matrix, months)

    def test_FA14_empty_test_set_is_not_reported_as_completed_evaluation(self):
        matrix = np.ones((1, 19))
        matrix[:, 15:] = np.nan
        with self.assertRaisesMessage(BusinessError, "kiểm tra"):
            evaluate_matrix(matrix, self.months())

    def test_FA15_no_future_candidates_do_not_publish_an_empty_forecast(self):
        matrix = np.ones((1, 19))
        matrix[:, -1] = np.nan
        with self.assertRaisesMessage(BusinessError, "dự báo"):
            evaluate_matrix(matrix, self.months())
