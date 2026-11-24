from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

import numpy as np
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse

from store.forecast.replenishment import month_add, suggestion_reasons
from store.forecast.research import (
    FEATURES,
    METHODS,
    generate_research,
    period_metrics,
    predict_origin,
    research_context,
    stock_scenario,
)
from store.models import (
    AuditEvent,
    DatasetVersion,
    Experiment,
    ForecastRun,
    ForecastUnit,
    ForecastValue,
    ModelResult,
    MonthlySales,
    ReplenishmentSuggestion,
    SaleOrder,
    StockEntry,
    StockPosting,
)
from store.services.documents import BusinessError
from store.tests.test_business import fixture


def research_fixture():
    admin, sales, warehouse, product, _, _, _ = fixture()
    ds = DatasetVersion.objects.create(
        code="RESEARCH-TEST",
        source_type="RESEARCH",
        status="VALIDATED",
        manifest_hash="a" * 64,
        coverage_start=date(2022, 1, 1),
        coverage_end=date(2023, 7, 1),
        created_by=admin,
        scope_definition={"key": "ALL_SOURCE_SITES_CHANNELS"},
    )
    exp = Experiment.objects.create(
        dataset_version=ds,
        status="SUCCEEDED",
        random_seed=42,
        feature_spec={"columns": FEATURES},
        split_config={"validation": ["2023-01", "2023-03"], "test": ["2023-04", "2023-07"]},
        model_configs={
            "rf_fixed": {"n_estimators": 200},
            "random_forest": {"max_depth": 5, "min_samples_leaf": 2},
        },
    )
    for method in METHODS:
        ModelResult.objects.create(
            experiment=exp, method=method, selected_on_validation=method == "naive"
        )
    for i in range(2):
        unit = ForecastUnit.objects.create(
            dataset_version=ds,
            external_key=f"SKU-{i}",
            label=f"MH{i:05d}",
            granularity="SKU",
            unit="đơn vị nguồn",
            scope_key="ALL_SOURCE_SITES_CHANNELS",
            internal_product=product if i == 0 else None,
        )
        for m in range(19):
            q = (3 + m % 4) if i == 0 else 0
            MonthlySales.objects.create(
                forecast_unit=unit,
                month=month_add(ds.coverage_start, m),
                positive_qty=q,
                negative_qty_abs=0,
                net_qty=q,
                target_qty=q,
                source_row_count=1,
                observation_status="OBSERVED",
            )
    return admin, sales, warehouse, ds


def small_predictions(matrix, months, config, seed):
    indices = np.array([0, 1])
    raw = {m: np.array([float(matrix[0, -1]), 0.0]) for m in METHODS}
    raw["linear"] = np.array([-1.25, 0.0])
    return indices, raw, 12


class ResearchModelTests(SimpleTestCase):
    def test_R01_recompute_uses_three_lags_and_keeps_unknown_unknown(self):
        months = [month_add(date(2022, 1, 1), i) for i in range(15)]
        matrix = np.array(
            [[3 + i % 4 for i in range(15)], [0] * 15, [np.nan] * 13 + [2, 3]], dtype=float
        )
        ids, raw, pairs = predict_origin(
            matrix, months, {"n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2}
        )
        self.assertEqual(ids.tolist(), [0, 1])
        self.assertEqual(raw["naive"][0], matrix[0, -1])
        self.assertEqual(raw["ma3"][0], matrix[0, -3:].mean())
        self.assertEqual(raw["naive"][1], 0)
        self.assertEqual(pairs, 24)

    def test_R02_invalid_calendar_and_nonfinite_history_rejected(self):
        months = [month_add(date(2022, 1, 1), i) for i in range(12)]
        config = {"n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2}
        for matrix, calendar in [
            (np.zeros((1, 8)), months[:8]),
            (np.ones((1, 12)), [months[0]] * 12),
            (np.full((1, 12), np.inf), months),
            (np.full((1, 12), -1), months),
        ]:
            with self.assertRaises(BusinessError):
                predict_origin(matrix, calendar, config)


class ResearchWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.warehouse, cls.ds = research_fixture()

    def run_forecast(self, target=date(2023, 8, 1)):
        with patch("store.forecast.research.predict_origin", side_effect=small_predictions):
            return generate_research(self.admin, self.ds.pk, target)

    def test_R03_new_runs_are_atomic_research_records_without_inventory_or_selection_changes(self):
        before = list(MonthlySales.objects.values())
        result = self.run_forecast()
        self.assertEqual(result["created_runs"], 4)
        self.assertEqual(ForecastRun.objects.filter(status="SUCCEEDED").count(), 4)
        self.assertEqual(ForecastValue.objects.count(), 8)
        self.assertEqual(list(MonthlySales.objects.values()), before)
        self.assertEqual(StockPosting.objects.count(), 0)
        self.assertEqual(StockEntry.objects.count(), 0)
        self.assertEqual(SaleOrder.objects.count(), 0)
        self.assertEqual(ReplenishmentSuggestion.objects.count(), 0)
        self.assertEqual(ModelResult.objects.get(selected_on_validation=True).method, "naive")
        self.ds.refresh_from_db()
        self.assertEqual(self.ds.source_type, "RESEARCH")
        linear = ForecastValue.objects.get(
            run__model_result__method="linear", forecast_unit__external_key="SKU-0"
        )
        self.assertEqual(linear.raw_value, Decimal("-1.25"))
        self.assertEqual(linear.nonnegative_value, 0)

    def test_R04_repeat_does_not_duplicate_or_overwrite_runs(self):
        first = self.run_forecast()
        count = AuditEvent.objects.count()
        second = self.run_forecast()
        self.assertEqual(first["runs"], second["runs"])
        self.assertEqual(second["created_runs"], 0)
        self.assertEqual(AuditEvent.objects.count(), count)

    def test_R05_target_actual_and_future_changes_do_not_enter_training_input(self):
        first = self.run_forecast(date(2023, 5, 1))
        MonthlySales.objects.filter(month__gte=date(2023, 5, 1)).update(
            positive_qty=999, net_qty=999, target_qty=999
        )
        second = self.run_forecast(date(2023, 5, 1))
        self.assertEqual(first["input_sha256"], second["input_sha256"])
        self.assertEqual(first["runs"], second["runs"])

    def test_R06_before_validation_and_after_source_targets_rejected(self):
        for target in [date(2023, 3, 1), date(2023, 9, 1)]:
            with self.assertRaises(BusinessError):
                generate_research(self.admin, self.ds.pk, target)
        self.assertFalse(ForecastRun.objects.exists())

    def test_R07_failure_during_audit_rolls_back_all_four_runs(self):
        with patch("store.forecast.research.audit", side_effect=RuntimeError("Test audit failure")):
            with self.assertRaises(RuntimeError):
                self.run_forecast()
        self.assertFalse(ForecastRun.objects.exists())
        self.assertFalse(ForecastValue.objects.exists())

    def test_R08_existing_conflicting_result_is_preserved(self):
        self.run_forecast()
        value = ForecastValue.objects.first()
        value.raw_value = Decimal("999")
        value.nonnegative_value = Decimal("999")
        value.save()
        with self.assertRaisesMessage(BusinessError, "khác lần tính lại"):
            self.run_forecast()
        value.refresh_from_db()
        self.assertEqual(value.nonnegative_value, Decimal("999"))

    def test_R09_authorization_and_csrf(self):
        for actor in [self.sales, self.warehouse]:
            with self.assertRaises(PermissionDenied):
                generate_research(actor, self.ds.pk, date(2023, 8, 1))
        self.client.force_login(self.sales)
        self.assertEqual(self.client.get(reverse("research_workspace")).status_code, 403)
        self.client.force_login(self.warehouse)
        self.assertEqual(self.client.get(reverse("research_workspace")).status_code, 200)
        self.assertEqual(
            self.client.post(reverse("research_workspace"), {"action": "run"}).status_code, 403
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(
            client.post(reverse("research_workspace"), {"action": "run"}).status_code, 403
        )

    def test_R10_actual_zero_is_scored_and_missing_actual_is_not_zero(self):
        result = self.run_forecast(date(2023, 7, 1))
        runs = {m: ForecastRun.objects.get(pk=pk) for m, pk in result["runs"].items()}
        scores = period_metrics(self.ds, date(2023, 7, 1), runs)
        for metric in scores:
            self.assertEqual(metric["n"], 2)
            self.assertEqual(metric["zero_n"], 1)
            self.assertEqual(metric["positive_n"], 1)
            self.assertEqual(metric["coverage"], 100)
        result = self.run_forecast()
        runs = {m: ForecastRun.objects.get(pk=pk) for m, pk in result["runs"].items()}
        self.assertTrue(
            all(
                m["mae"] is None and m["coverage"] is None and m["n"] == 0
                for m in period_metrics(self.ds, date(2023, 8, 1), runs)
            )
        )

    def test_R11_scenario_validates_counts_rounding_and_does_not_create_operational_suggestion(
        self,
    ):
        self.run_forecast()
        value = ForecastValue.objects.get(
            run__model_result__method="naive", forecast_unit__external_key="SKU-0"
        )
        value.nonnegative_value = Decimal("32.4")
        before = StockEntry.objects.count()
        self.assertEqual(stock_scenario(value, 14, 5, 6)["quantity"], 18)
        self.assertEqual(stock_scenario(value, 100, 0, 999)["quantity"], 0)
        for invalid in [-1, "1.5", "NaN", "Infinity", None, 2**31]:
            with self.assertRaises(BusinessError):
                stock_scenario(value, invalid, 5, 0)
        self.assertEqual(StockEntry.objects.count(), before)
        self.assertFalse(ReplenishmentSuggestion.objects.exists())
        self.assertTrue(suggestion_reasons(value))

    def test_R12_workspace_csv_and_default_list_stay_on_selected_method(self):
        self.run_forecast()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("research_workspace"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["predictions"]), 4)
        self.assertContains(response, "Chưa xác định")
        unit = self.ds.forecast_units.get(external_key="SKU-0")
        response = self.client.get(
            reverse("research_workspace"),
            {"dataset": self.ds.pk, "target": "2023-08", "unit": unit.pk, "export": "csv"},
        )
        self.assertIn("text/csv", response["Content-Type"])
        self.assertEqual(len(response.content.decode("utf-8-sig").splitlines()), 5)
        page = self.client.get(reverse("forecasts"))
        self.assertEqual(page.context["run"].model_result.method, "naive")

    def test_R13_scenario_post_records_assumptions_and_keeps_stock(self):
        self.run_forecast()
        unit = self.ds.forecast_units.get(external_key="SKU-0")
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("research_workspace"),
            {
                "action": "scenario",
                "dataset": self.ds.pk,
                "target": "2023-08",
                "unit": unit.pk,
                "scenario-method": "naive",
                "scenario-stock": 0,
                "scenario-safety": 5,
                "scenario-sold": 0,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["scenario"])
        self.assertTrue(AuditEvent.objects.filter(action="RESEARCH_STOCK_SCENARIO").exists())
        self.assertFalse(StockPosting.objects.exists())
        self.assertFalse(ReplenishmentSuggestion.objects.exists())


class ResearchConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_R14_two_identical_requests_publish_only_one_set_of_runs(self):
        admin, _, _, ds = research_fixture()
        barrier = Barrier(2)

        def predict(*args):
            barrier.wait(timeout=20)
            return small_predictions(*args)

        def worker():
            try:
                return generate_research(admin, ds.pk, date(2023, 8, 1))
            finally:
                connections.close_all()

        with patch("store.forecast.research.predict_origin", side_effect=predict):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(ForecastRun.objects.count(), 4)
        self.assertEqual(ForecastValue.objects.count(), 8)
        self.assertEqual(sorted(r["created_runs"] for r in results), [0, 4])
