from datetime import date

from django.test import SimpleTestCase

from store.forecast.metrics import point_metrics, training_scale


class ForecastMetricsTests(SimpleTestCase):
    def test_known_formula_and_bias_direction(self):
        history = [(date(2022, m, 1), q) for m, q in [(1, 2), (2, 4), (3, 6)]]
        scale = training_scale(history, date(2022, 4, 1))
        self.assertEqual(scale, 2)
        result = point_metrics([7], [5], [scale])
        for key, expected in [("mae", 2), ("rmse", 2), ("mase", 1), ("bias", -2)]:
            self.assertEqual(result[key], expected)
        self.assertAlmostEqual(result["wape_pct"], 200 / 7)
        self.assertEqual(result["mase_n"], 1)

    def test_zero_actuals_remain_in_mae_and_wape(self):
        result = point_metrics([0, 10], [4, 8], [None, 2])
        self.assertEqual(result["mae"], 3)
        self.assertEqual(result["wape_pct"], 60)
        self.assertEqual(result["mape_positive_pct"], 20)
        self.assertEqual(result["n_zero_actual"], 1)
        self.assertEqual(result["mase_coverage_pct"], 50)

    def test_undefined_denominators_are_not_zero_errors(self):
        result = point_metrics([0, 0], [1, 0], [0, None])
        for key in ["wape_pct", "mape_positive_pct", "mase"]:
            self.assertIsNone(result[key])
        self.assertEqual(result["mae"], 0.5)
        self.assertIsNone(point_metrics([], [])["mae"])

    def test_scale_is_calendar_based_and_strictly_before_target(self):
        history = [
            (date(2022, 1, 1), 2),
            (date(2022, 3, 1), 100),
            (date(2022, 4, 1), 104),
            (date(2022, 5, 1), 99999),
        ]
        self.assertEqual(training_scale(history, date(2022, 5, 1)), 4)
        self.assertIsNone(training_scale(history, date(2022, 3, 1)))

    def test_invalid_inputs_are_rejected(self):
        for actual, predicted, scale in [
            ([1], [], None),
            ([float("nan")], [1], None),
            ([1], [-1], None),
            ([1], [1], [-1]),
            ([1], [1], []),
        ]:
            with self.assertRaises(ValueError):
                point_metrics(actual, predicted, scale)
