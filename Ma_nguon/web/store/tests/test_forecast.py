import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
from django.test import TestCase, override_settings
from django.utils import timezone

from store.forecast.demand import generate_operational
from store.forecast.replenishment import evaluate_matrix, import_research, month_add
from store.models import *
from store.services.documents import BusinessError
from store.tests.test_business import fixture


class ForecastTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = fixture()

    def test_TC27_no_validation_lookahead_and_selection_frozen(self):
        months = [month_add(date(2022, 1, 1), i) for i in range(19)]
        a = np.array([[8 + (i % 4) for i in range(19)], [4 + (i % 3) for i in range(19)]], float)
        first = evaluate_matrix(a, months)
        changed = a.copy()
        changed[:, 15:] = 9999
        second = evaluate_matrix(changed, months)
        self.assertEqual(first["selected"], second["selected"])
        for method, metrics in first["validation"].items():
            for key, value in metrics.items():
                if isinstance(value, float):
                    self.assertAlmostEqual(value, second["validation"][method][key], places=10)
                else:
                    self.assertEqual(value, second["validation"][method][key])
        self.assertNotEqual(first["test"], second["test"])

    def test_TC28_common_pairs_zero_mape_and_unknown(self):
        months = [month_add(date(2022, 1, 1), i) for i in range(19)]
        a = np.zeros((2, 19))
        a[1, 17] = np.nan
        result = evaluate_matrix(a, months)
        for phase in ["validation", "test"]:
            counts = {m["n"] for m in result[phase].values()}
            self.assertEqual(len(counts), 1)
            for m in result[phase].values():
                self.assertIsNone(m["mape_positive_pct"])
                self.assertEqual(m["mae"], 0)
                self.assertEqual(m["n_zero_actual"], m["n"])
        self.assertNotIn(1, result["future"])

    def test_short_history_and_invalid_calendar_rejected(self):
        with self.assertRaises(BusinessError):
            evaluate_matrix(np.zeros((1, 10)), [month_add(date(2022, 1, 1), i) for i in range(10)])
        with self.assertRaises(BusinessError):
            evaluate_matrix(np.zeros((1, 19)), [date(2022, 1, 1)] * 19)

    def test_operational_demo_and_new_store_do_not_invent_history(self):
        guard = SystemGuard.objects.get(pk=1)
        guard.data_mode = "DEMO"
        guard.save()
        with self.assertRaisesMessage(BusinessError, "chưa được xác nhận"):
            generate_operational(self.admin, date(2023, 7, 1))
        guard.data_mode = "OPERATIONAL"
        guard.save()
        with self.assertRaisesMessage(BusinessError, "16 tháng"):
            generate_operational(self.admin, month_add(timezone.localdate().replace(day=1), -1))
        self.assertEqual(DatasetVersion.objects.count(), 0)

    def test_operational_pipeline_publishes_whole_run_and_preserves_stock(self):
        current = timezone.localdate().replace(day=1)
        cutoff = month_add(current, -1)
        begin = month_add(current, -21)
        old = timezone.make_aware(datetime(begin.year, begin.month, 1))
        SystemGuard.objects.filter(pk=1).update(initialized_at=old)
        Product.objects.update(created_at=old)
        d = generate_operational(self.admin, cutoff)
        self.assertEqual(d.source_type, "OPERATIONAL")
        self.assertEqual(d.status, "VALIDATED")
        self.assertEqual(ModelResult.objects.filter(experiment__dataset_version=d).count(), 4)
        self.assertEqual(d.forecast_units.get().granularity, "PRODUCT")
        self.assertEqual(StockPosting.objects.count(), 0)
        self.assertEqual(generate_operational(self.admin, cutoff).pk, d.pk)

    def miniature_research(self, root):
        def write(name, obj):
            (root / name).write_text(json.dumps(obj), encoding="utf-8")

        write(
            "source_manifest.json",
            [{"file": "MasterData\\Productmaster.xlsx", "bytes": 10, "sha256": "a" * 64}],
        )
        write(
            "khao_sat_du_lieu.json",
            {
                "unique_sites": 1,
                "observed_unit_months": 3,
                "unique_retained_product_ids": 1,
                "counts": {"retained_rows": 6},
                "master_rows": 1,
                "files": [],
            },
        )
        metrics = [
            {
                "method": m,
                "n": 1,
                "n_positive_actual": 1,
                "n_zero_actual": 0,
                "mae": 0,
                "rmse": 0,
                "mape_positive_pct": 0,
            }
            for m in ["naive", "ma3", "linear", "random_forest"]
        ]
        write(
            "lua_chon_truoc_kiem_tra.json",
            {
                "winner": "naive",
                "rf_config": {},
                "rf_fixed": {},
                "validation_metrics": metrics,
                "split": {
                    "initial_train": "before 2023-03",
                    "validation": "2023-03",
                    "test": "2023-04",
                },
            },
        )
        write(
            "tong_hop_thuc_nghiem.json",
            {
                "validation_metrics": metrics,
                "test_metrics": metrics,
                "selected_method": "naive",
                "future_research_forecast_count": 1,
                "selection_file_sha256": hashlib.sha256(
                    (root / "lua_chon_truoc_kiem_tra.json").read_bytes()
                ).hexdigest(),
            },
        )
        with (root / "luong_ban_theo_thang.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "unit_alias",
                    "product_id",
                    "month",
                    "positive_qty",
                    "negative_qty_abs",
                    "net_qty",
                    "source_rows",
                    "product_group",
                ]
            )
            for month in ["2023-03", "2023-04", "2023-07"]:
                w.writerow(["MH00001", "000ABC", month, 3, 1, 2, 2, "SAN"])
        for name, month in [
            ("du_doan_kiem_dinh.csv", "2023-03"),
            ("du_doan_kiem_tra.csv", "2023-04"),
        ]:
            with (root / name).open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(
                    ["product_id", "month", "actual", "naive", "ma3", "linear", "random_forest"]
                )
                w.writerow(["000ABC", month, 3, 3, 3, 3, 3])
        with (root / "du_bao_nghien_cuu_2023_08.csv").open(
            "w", newline="", encoding="utf-8-sig"
        ) as f:
            w = csv.writer(f)
            w.writerow(
                ["unit_alias", "product_id", "cutoff_month", "target_month", "method", "forecast"]
            )
            w.writerow(["MH00001", "000ABC", "2023-07", "2023-08", "naive", 3])

    def test_TC25_26_research_import_keeps_codes_flows_and_does_not_create_orders(self):
        with TemporaryDirectory() as t, override_settings(RESEARCH_RESULTS_DIR=Path(t)):
            self.miniature_research(Path(t))
            ds = import_research(self.admin)
            row = MonthlySales.objects.get(month=date(2023, 7, 1))
            self.assertEqual(row.positive_qty, 3)
            self.assertEqual(row.negative_qty_abs, 1)
            self.assertEqual(row.forecast_unit.external_key, "000ABC")
            self.assertEqual(row.forecast_unit.mapping_status, "UNVERIFIED")
            self.assertEqual(ds.source_type, "RESEARCH")
            self.assertEqual(SaleOrder.objects.count(), 0)
            self.assertEqual(StockPosting.objects.count(), 0)
            self.assertEqual(import_research(self.admin).pk, ds.pk)

    def test_TC32_failed_import_does_not_publish_partial_data(self):
        with TemporaryDirectory() as t, override_settings(RESEARCH_RESULTS_DIR=Path(t)):
            root = Path(t)
            self.miniature_research(root)
            (root / "du_bao_nghien_cuu_2023_08.csv").write_text(
                "product_id,forecast,method,target_month\n000ABC,-3,naive,2023-08\n",
                encoding="utf-8",
            )
            with self.assertRaises(BusinessError):
                import_research(self.admin)
            self.assertEqual(DatasetVersion.objects.count(), 0)
            self.assertEqual(MonthlySales.objects.count(), 0)
