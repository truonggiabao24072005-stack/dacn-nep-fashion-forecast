"""Recompute historical forecasts using only observations before the target month.

Model selection and hyperparameters stay frozen at the saved validation split.
Research results and explicit stock scenarios never post operational inventory.
"""

import json
import re
from datetime import date
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from hashlib import sha256

import numpy as np
from django.db import transaction
from django.utils import timezone

from store.forecast.metrics import point_metrics, training_scale
from store.forecast.replenishment import month_add, month_parse
from store.forecast.training import FEATURES, METHODS
from store.models import (
    AuditEvent,
    DatasetVersion,
    Experiment,
    ForecastRun,
    ForecastUnit,
    ForecastValue,
    ModelResult,
    MonthlySales,
    Role,
    SourceType,
)
from store.services.documents import BusinessError, audit, authorize

VERSION = "research-origin-v1"


def research_context(dataset, experiment_id=None):
    if dataset.source_type != SourceType.RESEARCH or dataset.status != "VALIDATED":
        raise BusinessError("Chọn phiên bản nghiên cứu đã được kiểm tra.")
    experiments = Experiment.objects.filter(dataset_version=dataset, status="SUCCEEDED")
    exp = (
        experiments.filter(pk=experiment_id).first()
        if experiment_id
        else experiments.order_by("-pk").first()
    )
    if not exp or exp.feature_spec.get("columns") != FEATURES:
        raise BusinessError("Chưa có cấu hình thực nghiệm phù hợp để chạy lại.")
    models = {m.method: m for m in exp.model_results.all()}
    selected = [m.method for m in models.values() if m.selected_on_validation]
    if set(models) != set(METHODS) or len(selected) != 1:
        raise BusinessError("Thực nghiệm phải có bốn phương pháp và một phương pháp đã chọn.")
    labels = re.findall(r"\d{4}-\d{2}", str(exp.split_config.get("validation", "")))
    if not labels:
        raise BusinessError("Thiếu mốc chốt lựa chọn trên Validation set.")
    validation_end = max(month_parse(value) for value in labels)
    first_target = month_add(validation_end, 1)
    last_target = month_add(dataset.coverage_end, 1)
    targets = []
    target = first_target
    while target <= last_target:
        targets.append(target)
        target = month_add(target, 1)
    if not targets:
        raise BusinessError("Chưa có kỳ dự báo sau thời điểm chọn mô hình.")
    return exp, models, selected[0], targets


def predict_origin(matrix, months, rf_config, random_seed=42, recipes=None):
    from store.forecast.training import predict_origin as train_predict

    try:
        return train_predict(matrix, months, rf_config, random_seed, recipes)
    except ValueError as exc:
        raise BusinessError(str(exc)) from exc


def _rf_config(exp):
    config = exp.model_configs
    fixed = config.get("rf_fixed", {})
    selected = config.get("random_forest", {})
    if (
        fixed.get("n_estimators", 200) != 200
        or selected.get("max_depth") != 5
        or selected.get("min_samples_leaf") != 2
        or exp.random_seed != 42
    ):
        raise BusinessError("Cấu hình Random Forest khác bộ thực nghiệm được hỗ trợ.")
    return {"n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2}


def generate_research(actor, dataset_id, target, experiment_id=None):
    authorize(actor, [Role.ADMIN])
    dataset = DatasetVersion.objects.get(pk=dataset_id)
    exp, models, selected, targets = research_context(dataset, experiment_id)
    if target not in targets:
        raise BusinessError("Kỳ phải sau Validation set và không vượt tháng kế tiếp của nguồn.")
    cutoff = month_add(target, -1)
    scope = dataset.scope_definition.get("key")
    units = list(ForecastUnit.objects.filter(dataset_version=dataset).order_by("external_key"))
    if not units or any(u.granularity != "SKU" or u.scope_key != scope for u in units):
        raise BusinessError("Cấp mã hoặc phạm vi nguồn không nhất quán.")
    months = []
    month = dataset.coverage_start
    while month <= cutoff:
        months.append(month)
        month = month_add(month, 1)
    positions = {u.pk: i for i, u in enumerate(units)}
    month_positions = {month: i for i, month in enumerate(months)}
    matrix = np.full((len(units), len(months)), np.nan)
    digest = sha256()
    config = _rf_config(exp)
    digest.update(
        json.dumps(
            {
                "version": VERSION,
                "dataset": dataset.manifest_hash,
                "cutoff": str(cutoff),
                "scope": scope,
                "features": FEATURES,
                "rf": config,
                "seed": exp.random_seed,
                "recipes": exp.model_configs.get("recipes"),
                "units": [u.external_key for u in units],
            },
            sort_keys=True,
        ).encode()
    )
    # The SQL cutoff is applied before loading model input. Actual target values
    # are read only later for scoring, after every prediction has been computed.
    rows = (
        MonthlySales.objects.filter(
            forecast_unit__dataset_version=dataset, month__gte=months[0], month__lte=cutoff
        )
        .order_by("forecast_unit__external_key", "month")
        .values_list("forecast_unit_id", "month", "target_qty", "observation_status")
    )
    for unit_id, month, quantity, observation in rows.iterator(chunk_size=4000):
        if observation not in ["OBSERVED", "VERIFIED_ZERO"] or quantity is None:
            continue
        matrix[positions[unit_id], month_positions[month]] = float(quantity)
        digest.update(
            f"{units[positions[unit_id]].external_key}|{month}|{quantity}|{observation}\n".encode()
        )
    input_hash = digest.hexdigest()
    recipes = exp.model_configs.get("recipes")
    if recipes:
        indices, raw, train_pairs = predict_origin(
            matrix, months, config, exp.random_seed, recipes=recipes
        )
    else:
        indices, raw, train_pairs = predict_origin(matrix, months, config, exp.random_seed)
    expected = {
        method: {
            units[int(i)].pk: (
                Decimal(str(v)).quantize(Decimal(".0001")),
                Decimal(str(max(0.0, float(v)))).quantize(Decimal(".0001")),
            )
            for i, v in zip(indices, values)
        }
        for method, values in raw.items()
    }
    with transaction.atomic():
        actor = authorize(actor, [Role.ADMIN], lock=True)
        locked = DatasetVersion.objects.select_for_update().get(pk=dataset.pk)
        if locked.status != "VALIDATED" or locked.manifest_hash != dataset.manifest_hash:
            raise BusinessError("Phiên bản nguồn vừa thay đổi; cần chạy lại.")
        run_ids = {}
        created = 0
        for method in METHODS:
            run = (
                ForecastRun.objects.filter(
                    model_result=models[method],
                    cutoff_month=cutoff,
                    target_month=target,
                    scope_key=scope,
                    status="SUCCEEDED",
                )
                .order_by("pk")
                .first()
            )
            if run:
                saved = {
                    r.forecast_unit_id: (r.raw_value, r.nonnegative_value) for r in run.values.all()
                }
                if saved != expected[method]:
                    raise BusinessError(
                        "Kết quả cùng kỳ đã lưu khác lần tính lại; giữ nguyên để đối chiếu."
                    )
            else:
                run = ForecastRun.objects.create(
                    model_result=models[method],
                    cutoff_month=cutoff,
                    target_month=target,
                    scope_key=scope,
                    status="RUNNING",
                )
                ForecastValue.objects.bulk_create(
                    [
                        ForecastValue(
                            run=run,
                            forecast_unit_id=unit_id,
                            raw_value=pair[0],
                            nonnegative_value=pair[1],
                            result_status="VALID",
                        )
                        for unit_id, pair in expected[method].items()
                    ],
                    batch_size=1000,
                )
                run.status = "SUCCEEDED"
                run.completed_at = timezone.now()
                run.save(update_fields=["status", "completed_at"])
                created += 1
            run_ids[method] = run.pk
        if created:
            audit(
                actor,
                "RUN_RESEARCH_FORECAST",
                dataset,
                {
                    "version": VERSION,
                    "input_sha256": input_hash,
                    "target": str(target),
                    "cutoff": str(cutoff),
                    "scope": scope,
                    "runs": run_ids,
                    "training_pairs": train_pairs,
                    "experiment_id": exp.pk,
                    "forecasted_skus": len(indices),
                    "selected_on_validation": selected,
                    "inventory_changed": False,
                    "new_model_selection": False,
                },
                reason="Chạy lại bốn phương pháp trên dữ liệu đến mốc chốt, giữ lựa chọn trên Validation set.",
            )
    return {
        "runs": run_ids,
        "created_runs": created,
        "forecasted_skus": len(indices),
        "input_sha256": input_hash,
        "training_pairs": train_pairs,
        "selected": selected,
    }


def research_runs(dataset, target, experiment_id=None):
    _, models, selected, _ = research_context(dataset, experiment_id)
    runs = {}
    for method in METHODS:
        run = (
            ForecastRun.objects.filter(
                model_result=models[method],
                cutoff_month=month_add(target, -1),
                target_month=target,
                status="SUCCEEDED",
                scope_key=dataset.scope_definition.get("key"),
            )
            .order_by("pk")
            .first()
        )
        if run:
            runs[method] = run
    return runs, selected


def period_metrics(dataset, target, runs):
    actual = dict(
        MonthlySales.objects.filter(
            forecast_unit__dataset_version=dataset,
            month=target,
            target_qty__isnull=False,
            observation_status__in=["OBSERVED", "VERIFIED_ZERO"],
        ).values_list("forecast_unit_id", "target_qty")
    )
    predictions = {
        method: dict(
            run.values.filter(result_status="VALID").values_list(
                "forecast_unit_id", "nonnegative_value"
            )
        )
        for method, run in runs.items()
    }
    common = set(actual)
    for values in predictions.values():
        common &= set(values)
    common = sorted(common)
    histories = {key: [] for key in common}
    for key, month, qty in MonthlySales.objects.filter(
        forecast_unit_id__in=common,
        month__lt=target,
        target_qty__isnull=False,
        observation_status__in=["OBSERVED", "VERIFIED_ZERO"],
    ).values_list("forecast_unit_id", "month", "target_qty"):
        histories[key].append((month, qty))
    scales = [training_scale(histories[key], target) for key in common]
    result = []
    for method in METHODS:
        if method not in runs:
            continue
        metrics = point_metrics(
            [actual[key] for key in common], [predictions[method][key] for key in common], scales
        )
        metrics.update(
            {
                "method": method,
                "actual_n": len(actual),
                "coverage": len(common) * 100 / len(actual) if actual else None,
                "positive_n": metrics["n_positive_actual"],
                "zero_n": metrics["n_zero_actual"],
            }
        )
        result.append(metrics)
    return result


def stock_scenario(value, stock, safety, sold):
    if (
        value.forecast_unit.dataset_version.source_type != SourceType.RESEARCH
        or value.result_status != "VALID"
    ):
        raise BusinessError("Chỉ tính tình huống từ Forecast nghiên cứu hợp lệ.")
    values = []
    for raw in [stock, safety, sold]:
        try:
            quantity = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            raise BusinessError("Số lượng phải là số nguyên không âm.") from None
        if (
            not quantity.is_finite()
            or quantity < 0
            or quantity != quantity.to_integral_value()
            or quantity > 2_147_483_647
        ):
            raise BusinessError("Số lượng phải là số nguyên không âm trong giới hạn.")
        values.append(int(quantity))
    stock, safety, sold = values
    forecast = value.nonnegative_value
    if forecast is None or not forecast.is_finite() or forecast < 0:
        raise BusinessError("Forecast chưa hợp lệ.")
    remaining = max(Decimal(0), forecast - sold)
    quantity = max(0, int((remaining + safety - stock).to_integral_value(rounding=ROUND_CEILING)))
    if quantity > 2_147_483_647:
        raise BusinessError("Lượng nhập vượt giới hạn.")
    return {
        "forecast": forecast,
        "remaining": remaining,
        "stock": stock,
        "safety": safety,
        "sold": sold,
        "quantity": quantity,
        "unit": value.forecast_unit.unit,
        "assumptions_only": True,
    }
