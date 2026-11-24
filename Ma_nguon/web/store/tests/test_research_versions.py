from datetime import date
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from store.forecast.experiments import VERSION, install_experiment
from store.forecast.features import fit_recipe
from store.forecast.replenishment import month_add
from store.forecast.research import METHODS, predict_origin, research_context
from store.models import Experiment, ForecastRun, ModelResult
from store.services.documents import BusinessError
from store.tests.test_research_workspace import research_fixture


class ResearchFeatureTests(SimpleTestCase):
    def test_log_target_is_inverted_to_quantity_units(self):
        # Constant target gives an exact, independently known inverse transform.
        X = np.array([[1, 2, 3, 2, m] for m in range(1, 10)], dtype=float)
        result = fit_recipe(
            {"method": "linear", "features": "log", "target": "log"}, X, np.full(9, 7.0), X[-2:]
        )
        np.testing.assert_allclose(result, [7, 7], atol=1e-10)

    def test_recipe_cannot_substitute_another_model_family(self):
        matrix = np.ones((1, 15))
        recipes = {
            method: {"method": method, "features": "raw", "target": "raw", "depth": 5}
            for method in METHODS
        }
        recipes["random_forest"]["method"] = "naive"
        with self.assertRaises(BusinessError):
            predict_origin(
                matrix, [month_add(date(2022, 1, 1), i) for i in range(15)], {}, recipes=recipes
            )


class ResearchVersionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.warehouse, cls.ds = research_fixture()

    def checked(self):
        recipes = {
            m: {"method": m, "features": "raw", "target": "raw", "depth": 5} for m in METHODS
        }
        selection = {
            "recipe_winners": recipes,
            "selected_method": "random_forest",
            "frozen_at": "2026-11-08",
            "source_monthly_sha256": "a" * 64,
            "test_disclosure": "exploratory",
        }
        metrics = {m: {"mae": 1, "n": 2} for m in METHODS}
        return selection, metrics, metrics, {"evaluation_metrics.json": "b" * 64}

    def test_installer_preserves_original_and_is_idempotent(self):
        original = list(ModelResult.objects.values())
        with patch("store.forecast.experiments.validate_artifacts", return_value=self.checked()):
            exp, created = install_experiment(self.admin, self.ds.pk)
            same, again = install_experiment(self.admin, self.ds.pk)
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(exp.pk, same.pk)
        self.assertEqual(exp.model_configs["research_version"], VERSION)
        self.assertEqual(
            list(ModelResult.objects.filter(experiment_id=original[0]["experiment_id"]).values()),
            original,
        )
        self.assertEqual(ForecastRun.objects.count(), 0)
        self.assertEqual(research_context(self.ds)[2], "random_forest")
        self.assertEqual(research_context(self.ds, original[0]["experiment_id"])[2], "naive")
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("research_workspace"), {"dataset": self.ds.pk, "experiment": exp.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nhu cầu dự đoán")
        self.assertNotContains(response, "Validation MAE")
        legacy = self.client.get(
            reverse("research_workspace"),
            {"dataset": self.ds.pk, "experiment": original[0]["experiment_id"]},
        )
        self.assertEqual(legacy.context["experiment"].pk, exp.pk)
        self.assertEqual(legacy.context["selected_method"], "random_forest")

    def test_audit_failure_rolls_back_new_experiment(self):
        before = (Experiment.objects.count(), ModelResult.objects.count())
        with patch(
            "store.forecast.experiments.validate_artifacts", return_value=self.checked()
        ), patch("store.forecast.experiments.audit", side_effect=BusinessError("audit failure")):
            with self.assertRaises(BusinessError):
                install_experiment(self.admin, self.ds.pk)
        self.assertEqual((Experiment.objects.count(), ModelResult.objects.count()), before)

    def test_artifact_change_cannot_overwrite_installed_version(self):
        with patch("store.forecast.experiments.validate_artifacts", return_value=self.checked()):
            exp, _ = install_experiment(self.admin, self.ds.pk)
        checked = list(self.checked())
        checked[-1] = {"evaluation_metrics.json": "c" * 64}
        with patch("store.forecast.experiments.validate_artifacts", return_value=checked):
            with self.assertRaises(BusinessError):
                install_experiment(self.admin, self.ds.pk)
        exp.refresh_from_db()
        self.assertEqual(exp.model_configs["artifact_hashes"]["evaluation_metrics.json"], "b" * 64)
