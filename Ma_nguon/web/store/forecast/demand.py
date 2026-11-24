"""Tạo dự báo từ lịch sử ghi sổ đã đóng kỳ của cửa hàng."""

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256

import numpy as np
from django.db import transaction
from django.db.models import F, Value
from django.utils import timezone

from store.forecast.replenishment import evaluate_matrix, month_add
from store.models import (
    DatasetVersion,
    Experiment,
    ForecastRun,
    ForecastUnit,
    ForecastValue,
    ModelResult,
    MonthlySales,
    Product,
    Role,
    SaleLine,
    SourceType,
    Status,
    SystemGuard,
)
from store.services.documents import BusinessError, audit, authorize
from store.services.reports import period_bounds


def generate_operational(actor, cutoff):
    authorize(actor, [Role.ADMIN])
    guard = SystemGuard.objects.get(pk=1)
    if guard.data_mode != "OPERATIONAL":
        raise BusinessError(
            "Cơ sở dữ liệu chưa được xác nhận cho ghi sổ vận hành. Hãy khởi tạo cửa hàng riêng trước khi tổng hợp lịch sử bán."
        )
    current = timezone.localdate().replace(day=1)
    if cutoff.day != 1 or cutoff >= current:
        raise BusinessError("Chỉ được dùng tháng lịch đã đóng kỳ, trước tháng hiện tại.")
    first = month_add(timezone.localtime(guard.initialized_at).date().replace(day=1), 1)
    months = []
    m = first
    while m <= cutoff:
        months.append(m)
        m = month_add(m, 1)
    if len(months) < 16:
        raise BusinessError(
            "Chưa đủ 16 tháng đóng kỳ kể từ khi bắt đầu ghi sổ. Chưa tạo kết quả dự báo."
        )
    months = months[-36:]
    closed_end = timezone.make_aware(datetime.combine(month_add(cutoff, 1), time.min))
    products = list(Product.objects.filter(created_at__lt=closed_end).order_by("pk"))
    if not products:
        raise BusinessError("Chưa có sản phẩm trong lịch sử đóng kỳ.")
    a, b = period_bounds(months[0], month_add(cutoff, 1) - timedelta(days=1))
    fields = ["flow", "pid", "event_at", "qty"]
    positive = (
        SaleLine.objects.filter(
            sale__status=Status.POSTED, sale__posted_at__gte=a, sale__posted_at__lt=b
        )
        .annotate(
            flow=Value("POS"),
            pid=F("variant__product_id"),
            event_at=F("sale__posted_at"),
            qty=F("quantity"),
        )
        .values(*fields)
    )
    negative = (
        SaleLine.objects.filter(
            sale__corrections__status=Status.POSTED,
            sale__corrections__posted_at__gte=a,
            sale__corrections__posted_at__lt=b,
        )
        .annotate(
            flow=Value("NEG"),
            pid=F("variant__product_id"),
            event_at=F("sale__corrections__posted_at"),
            qty=F("quantity"),
        )
        .values(*fields)
    )
    sums = {}
    for r in positive.union(negative, all=True):
        key = (r["pid"], timezone.localtime(r["event_at"]).date().replace(day=1))
        item = sums.setdefault(key, {"pos": 0, "neg": 0, "rows": 0})
        item["pos" if r["flow"] == "POS" else "neg"] += r["qty"]
        item["rows"] += 1
    matrix = np.full((len(products), len(months)), np.nan)
    records = []
    for i, p in enumerate(products):
        available = month_add(timezone.localtime(p.created_at).date().replace(day=1), 1)
        for j, m in enumerate(months):
            if m < available:
                continue
            item = sums.get((p.pk, m), {"pos": 0, "neg": 0, "rows": 0})
            matrix[i, j] = item["pos"]
            records.append({"product": p.pk, "month": str(m), **item})
    payload = {
        "scope": "STORE_MAIN",
        "months": [str(m) for m in months],
        "records": records,
        "products": [(p.pk, p.unit) for p in products],
        "source_type": "OPERATIONAL",
        "policy": "closed-positive-flow-v2",
        "model": "rf200-depth5-leaf2-seed42",
        "prediction_values": "raw_and_nonnegative_v1",
    }
    digest = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    code = "VH-" + digest[:24]
    existing = DatasetVersion.objects.filter(code=code, status="VALIDATED").first()
    if existing:
        return existing
    scores = evaluate_matrix(matrix, months)
    with transaction.atomic():
        actor = authorize(actor, [Role.ADMIN], lock=True)
        existing = DatasetVersion.objects.filter(code=code, status="VALIDATED").first()
        if existing:
            return existing
        ds = DatasetVersion.objects.create(
            code=code,
            source_type=SourceType.OPERATIONAL,
            manifest_hash=digest,
            coverage_start=months[0],
            coverage_end=cutoff,
            created_by=actor,
            status="DRAFT",
            scope_definition={
                "key": "STORE_MAIN",
                "granularity": "PRODUCT",
                "description": "Một cửa hàng, tổng biến thể cùng sản phẩm và đơn vị.",
            },
            cleaning_config={
                "target": "positive_flow",
                "negative": "corrections_separate",
                "zero": "verified_complete_operational_month",
                "max_months": 36,
                "prediction_values": "raw_and_nonnegative_v1",
            },
        )
        units = {}
        for p in products:
            units[p.pk] = ForecastUnit.objects.create(
                dataset_version=ds,
                external_key=f"PRODUCT:{p.pk}",
                label=p.name,
                granularity="PRODUCT",
                unit=p.unit,
                scope_key="STORE_MAIN",
                internal_product=p,
                mapping_status="VERIFIED",
                mapping_evidence="Khóa Product và SaleLine.variant.product trong cùng dữ liệu cửa hàng.",
            )
        MonthlySales.objects.bulk_create(
            [
                MonthlySales(
                    forecast_unit=units[r["product"]],
                    month=date.fromisoformat(r["month"]),
                    positive_qty=r["pos"],
                    negative_qty_abs=r["neg"],
                    net_qty=r["pos"] - r["neg"],
                    target_qty=r["pos"],
                    observation_status="OBSERVED" if r["rows"] else "VERIFIED_ZERO",
                    source_row_count=r["rows"],
                )
                for r in records
            ],
            batch_size=1000,
        )
        exp = Experiment.objects.create(
            dataset_version=ds,
            status="SUCCEEDED",
            target_definition={"target": "positive_flow", "granularity": "PRODUCT"},
            eligibility_policy={"min_valid_training_pairs": 6, "consecutive_lags": 3},
            split_config={
                "validation": [str(m) for m in months[-7:-4]],
                "test": [str(m) for m in months[-4:]],
                "scheme": "rolling_origin",
            },
            feature_spec={"columns": ["lag1", "lag2", "lag3", "ma3", "month_number"]},
            model_configs={
                "rf": {"n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2},
                "selection": "validation_mae",
            },
            random_seed=42,
        )
        results = {}
        for method in ["naive", "ma3", "linear", "random_forest"]:
            results[method] = ModelResult.objects.create(
                experiment=exp,
                method=method,
                selected_on_validation=method == scores["selected"],
                validation_metrics=scores["validation"][method],
                test_metrics=scores["test"][method],
                scored_pair_manifest={"policy": "same_observed_pairs_all_methods"},
            )
        run = ForecastRun.objects.create(
            model_result=results[scores["selected"]],
            cutoff_month=cutoff,
            target_month=month_add(cutoff, 1),
            scope_key="STORE_MAIN",
        )
        values = []
        for i, p in enumerate(products):
            value = scores["future"].get(i)
            raw = scores["future_raw"].get(i)
            if value is not None and (
                not np.isfinite(value)
                or not 0 <= value < 1e14
                or raw is None
                or not np.isfinite(raw)
                or not -1e14 < raw < 1e14
            ):
                raise BusinessError("Dự báo nằm ngoài giới hạn lưu trữ. Chưa công bố bộ kết quả.")
            rounded = Decimal(str(value)).quantize(Decimal(".0001")) if value is not None else None
            rounded_raw = (
                Decimal(str(raw)).quantize(Decimal(".0001")) if value is not None else None
            )
            values.append(
                ForecastValue(
                    run=run,
                    forecast_unit=units[p.pk],
                    raw_value=rounded_raw,
                    nonnegative_value=rounded,
                    result_status="VALID" if value is not None else "INSUFFICIENT_DATA",
                )
            )
        ForecastValue.objects.bulk_create(values)
        run.status = "SUCCEEDED"
        run.completed_at = timezone.now()
        run.save()
        ds.status = "VALIDATED"
        ds.save()
        audit(
            actor,
            "GENERATE_OPERATIONAL_FORECAST",
            ds,
            {"selected": scores["selected"], "products": len(products)},
        )
        return ds
