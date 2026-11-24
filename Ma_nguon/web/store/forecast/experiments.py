"""Install a separate, reproducible research experiment without altering v1."""

import csv
import io
import json
import math
from datetime import date
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.db import transaction

from store.forecast.metrics import point_metrics, training_scale
from store.forecast.research import FEATURES, METHODS
from store.models import DatasetVersion, Experiment, ModelResult, MonthlySales, Role
from store.services.documents import BusinessError, audit, authorize

VERSION = "feature-log-20261108"
ARTIFACT_FOLDER = "research_artifacts/" + VERSION
FILES = [
    "selection_before_test.json",
    "results.json",
    "test_predictions.csv",
    "future_predictions.csv",
    "evaluation_metrics.json",
    "code_provenance.json",
]


def _require(condition, message):
    if not condition:
        raise BusinessError(message)


def validate_artifacts(dataset):
    folder = Path(settings.RESEARCH_ARTIFACTS_DIR)
    blobs = {name: (folder / name).read_bytes() for name in FILES}
    selection = json.loads(blobs["selection_before_test.json"])
    result = json.loads(blobs["results.json"])
    evaluation = json.loads(blobs["evaluation_metrics.json"])
    hashes = {name: sha256(blob).hexdigest() for name, blob in blobs.items()}
    _require(
        result["selection_file_sha256"] == hashes["selection_before_test.json"]
        and selection == result["selection"],
        "Dấu kiểm tra lựa chọn mô hình không khớp.",
    )
    source = (
        dataset.experiments.filter(status="SUCCEEDED", model_configs__recipes__isnull=True)
        .order_by("pk")
        .first()
    )
    _require(source is not None, "Cần có bản nghiên cứu gốc trước khi nạp bản cải tiến.")
    source_hash = source.model_configs.get("artifact_hashes", {}).get("luong_ban_theo_thang.csv")
    monthly_blob = (Path(settings.RESEARCH_RESULTS_DIR) / "luong_ban_theo_thang.csv").read_bytes()
    monthly_hash = sha256(monthly_blob).hexdigest()
    if source_hash is None:
        source_hash = monthly_hash
    _require(
        source_hash == selection["source_monthly_sha256"] == evaluation["source_monthly_sha256"],
        "Bản cải tiến không dùng cùng dữ liệu tháng với bản gốc.",
    )
    _require(source_hash == monthly_hash, "Tệp dữ liệu tháng gốc vừa thay đổi.")
    _require(
        evaluation["versions"]["feature_log"]["prediction_sha256"]
        == hashes["test_predictions.csv"],
        "CSV dự đoán không khớp bộ Metrics.",
    )
    _require(
        selection["criterion"] == "Validation MAE"
        and selection["validation_months"] == ["2023-01", "2023-02", "2023-03"]
        and selection["test_months"] == ["2023-04", "2023-05", "2023-06", "2023-07"]
        and selection["target_definition"] == "positive_flow",
        "Phạm vi đánh giá bị thay đổi.",
    )
    recipes = selection["recipe_winners"]
    _require(set(recipes) == set(METHODS), "Thiếu một trong bốn phương pháp.")
    validation = {}
    for method in METHODS:
        recipe = recipes[method]
        _require(recipe["method"] == method, "Tên phương pháp không khớp cấu hình.")
        validation[method] = selection["validation_scores"][recipe["id"]]
        _require(validation[method]["n"] == 4561, "Tập Validation khác bản đã chốt.")
        _require(
            all(math.isfinite(validation[method][k]) for k in ["mae", "rmse", "bias", "wape_pct"]),
            "Metrics Validation không hợp lệ.",
        )
    winner = min(METHODS, key=lambda m: (validation[m]["mae"], METHODS.index(m)))
    _require(
        winner == selection["selected_method"] == result["selected_method"],
        "Lựa chọn không khớp Validation MAE.",
    )
    rows = list(csv.DictReader(io.StringIO(blobs["test_predictions.csv"].decode("utf-8-sig"))))
    keys = [(r["product_id"], r["month"]) for r in rows]
    _require(len(keys) == len(set(keys)) == 7955, "Tập Test phải có 7.955 cặp duy nhất.")
    histories = {}
    actuals = {}
    for key, month, qty, status in MonthlySales.objects.filter(
        forecast_unit__dataset_version=dataset, month__lte=date(2023, 7, 1)
    ).values_list("forecast_unit__external_key", "month", "target_qty", "observation_status"):
        if qty is not None and status in ["OBSERVED", "VERIFIED_ZERO"]:
            histories.setdefault(key, []).append((month, qty))
            actuals[(key, month.strftime("%Y-%m"))] = float(qty)
    _require(
        all(key in actuals and actuals[key] == float(r["actual"]) for key, r in zip(keys, rows)),
        "Actual của CSV không khớp dữ liệu trong cơ sở dữ liệu.",
    )
    original_monthly = list(csv.DictReader(io.StringIO(monthly_blob.decode("utf-8-sig"))))
    _require(
        len(original_monthly) == len(actuals)
        and all(
            actuals.get((r["product_id"], r["month"])) == float(r["positive_qty"])
            for r in original_monthly
        ),
        "Dữ liệu tháng trong SQL khác tệp nguồn đã chốt.",
    )
    scales = [
        training_scale(histories[r["product_id"]], date.fromisoformat(r["month"] + "-01"))
        for r in rows
    ]
    metrics = {}
    for method in METHODS:
        calculated = point_metrics([r["actual"] for r in rows], [r[method] for r in rows], scales)
        saved = evaluation["versions"]["feature_log"]["test_metrics"][method]
        for key, value in calculated.items():
            expected = saved[key]
            _require(
                (value is None and expected is None)
                or (
                    value is not None
                    and expected is not None
                    and math.isclose(value, expected, rel_tol=1e-10, abs_tol=1e-10)
                ),
                "Metrics Test không khớp công thức hoặc CSV dự đoán.",
            )
        metrics[method] = saved
    return selection, validation, metrics, hashes


def install_experiment(actor, dataset_id):
    authorize(actor, [Role.ADMIN])
    dataset = DatasetVersion.objects.get(pk=dataset_id)
    _require(
        dataset.source_type == "RESEARCH" and dataset.status == "VALIDATED",
        "Chỉ nạp vào bộ nghiên cứu đã được kiểm tra.",
    )
    selection, validation, metrics, hashes = validate_artifacts(dataset)
    with transaction.atomic():
        actor = authorize(actor, [Role.ADMIN], lock=True)
        DatasetVersion.objects.select_for_update().get(pk=dataset.pk)
        existing = dataset.experiments.filter(model_configs__research_version=VERSION).first()
        if existing:
            _require(
                existing.model_configs["artifact_hashes"] == hashes,
                "Phiên bản này đã tồn tại với nội dung khác; không ghi đè.",
            )
            return existing, False
        exp = Experiment.objects.create(
            dataset_version=dataset,
            status="SUCCEEDED",
            random_seed=42,
            target_definition={"target": "positive_flow", "unit": "source_product_id"},
            eligibility_policy={
                "min_valid_training_pairs": 6,
                "three_consecutive_calendar_lags": True,
            },
            split_config={
                "train": "2022",
                "validation": ["2023-01", "2023-03"],
                "test": ["2023-04", "2023-07"],
                "scheme": "rolling_origin",
            },
            feature_spec={
                "columns": FEATURES,
                "transforms": "log1p lags/target; sin/cos calendar month",
            },
            model_configs={
                "research_version": VERSION,
                "recipes": selection["recipe_winners"],
                "selected_before_test": selection["selected_method"],
                "rf_fixed": {"n_estimators": 200},
                "random_forest": {"max_depth": 5, "min_samples_leaf": 2},
                "artifact_hashes": hashes,
                "source_monthly_sha256": selection["source_monthly_sha256"],
                "frozen_at": selection["frozen_at"],
                "test_disclosure": selection["test_disclosure"],
                "metric_version": "retail-point-metrics-v1",
            },
        )
        for method in METHODS:
            ModelResult.objects.create(
                experiment=exp,
                method=method,
                selected_on_validation=method == selection["selected_method"],
                validation_metrics=validation[method],
                test_metrics=metrics[method],
                scored_pair_manifest={
                    "validation_n": 4561,
                    "test_n": 7955,
                    "shared_pairs": True,
                    "mase_lag": 1,
                    "aggregation": "pair-weighted",
                    "test_previously_inspected": True,
                },
                artifact_path=ARTIFACT_FOLDER + "/evaluation_metrics.json",
                artifact_hash=hashes["evaluation_metrics.json"],
            )
        audit(
            actor,
            "INSTALL_RESEARCH_EXPERIMENT",
            exp,
            {"version": VERSION, "artifact_hashes": hashes, "original_preserved": True},
            reason="Lưu riêng bản cải tiến đã chọn theo Validation MAE; Test là so sánh thăm dò cùng kỳ.",
        )
    return exp, True
