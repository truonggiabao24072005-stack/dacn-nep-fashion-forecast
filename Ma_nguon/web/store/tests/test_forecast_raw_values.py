from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import numpy as np
from django.test import TestCase
from django.utils import timezone

from store.forecast.demand import generate_operational
from store.forecast.replenishment import evaluate_matrix, month_add
from store.models import Product, StockPosting, SystemGuard
from store.tests.test_business import fixture


class ForecastRawValueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, _, _, cls.product, _, _, _ = fixture()

    def test_declining_history_keeps_signed_linear_prediction(self):
        months = [month_add(date(2022, 1, 1), i) for i in range(16)]
        result = evaluate_matrix(np.arange(15, -1, -1, dtype=float)[None, :], months)
        self.assertEqual(result["selected"], "linear")
        self.assertLess(result["future_raw"][0], 0)
        self.assertEqual(result["future"][0], 0)
        self.assertEqual(result["future"][0], max(0, result["future_raw"][0]))

    def test_operational_publish_keeps_raw_value_and_nonnegative_quantity_separate(self):
        cutoff = month_add(timezone.localdate().replace(day=1), -1)
        begin = month_add(cutoff, -21)
        started = timezone.make_aware(datetime(begin.year, begin.month, 1))
        SystemGuard.objects.filter(pk=1).update(initialized_at=started)
        Product.objects.update(created_at=started)
        metric = {
            "n": 1,
            "mae": 0,
            "rmse": 0,
            "mape_positive_pct": None,
            "n_positive_actual": 0,
            "n_zero_actual": 1,
        }
        scores = {
            "selected": "linear",
            "future": {0: 0},
            "future_raw": {0: -1.25},
            "validation": {name: metric for name in ["naive", "ma3", "linear", "random_forest"]},
            "test": {name: metric for name in ["naive", "ma3", "linear", "random_forest"]},
        }
        with patch("store.forecast.demand.evaluate_matrix", return_value=scores):
            dataset = generate_operational(self.admin, cutoff)
        value = dataset.forecast_units.get().forecasts.get()
        self.assertEqual(value.raw_value, Decimal("-1.25"))
        self.assertEqual(value.nonnegative_value, Decimal("0"))
        self.assertEqual(value.result_status, "VALID")
        self.assertEqual(StockPosting.objects.count(), 0)
