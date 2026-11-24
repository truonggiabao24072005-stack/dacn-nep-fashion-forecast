import re
from datetime import date, datetime, time
from decimal import ROUND_CEILING, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from store.forecast.validation import read_bundle
from store.models import (
    DatasetVersion,
    Experiment,
    ExternalSkuMap,
    ForecastRun,
    ForecastUnit,
    ForecastValue,
    ModelResult,
    MonthlySales,
    Product,
    ReplenishmentPolicy,
    ReplenishmentSuggestion,
    Role,
    SaleLine,
    SourceFile,
    SourceType,
    Status,
    StockBalance,
    Variant,
)
from store.services.documents import BusinessError, _lock_stock, audit, authorize


def month_add(d, offset):
    try:
        n = d.year * 12 + d.month - 1 + offset
        return date(n // 12, n % 12 + 1, 1)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise BusinessError("Tháng nằm ngoài phạm vi lịch được hỗ trợ.") from None


def month_parse(text):
    try:
        d = datetime.strptime(text, "%Y-%m").date().replace(day=1)
        if d.strftime("%Y-%m") != text:
            raise ValueError
        return d
    except (TypeError, ValueError):
        raise BusinessError("Tháng phải có dạng YYYY-MM.")


@transaction.atomic
def import_research(actor):
    authorize(actor, [Role.ADMIN])
    root = settings.RESEARCH_RESULTS_DIR
    checked = read_bundle(root)
    digest = checked["digest"]
    name = "NC-" + digest[:32]
    existing = DatasetVersion.objects.filter(code=name).first()
    if existing:
        if existing.manifest_hash != digest or existing.status != "VALIDATED":
            raise BusinessError("Phiên bản dữ liệu đã có nhưng chưa hoàn tất kiểm tra.")
        return existing
    survey = checked["survey"]
    summary = checked["summary"]
    selected = checked["selection"]
    dataset = DatasetVersion.objects.create(
        code=name,
        source_type=SourceType.RESEARCH,
        manifest_hash=digest,
        coverage_start=checked["coverage_start"],
        coverage_end=checked["cutoff"],
        created_by=actor,
        scope_definition={
            "key": "ALL_SOURCE_SITES_CHANNELS",
            "description": f"Toàn bộ địa điểm và kênh của {len(survey['files'])} tệp bán hàng, không phải cửa hàng đang vận hành.",
            "granularity": "SKU",
            "sites": survey["unique_sites"],
            "unmatched_rows": survey["counts"].get("unmatched_master_rows", 0),
        },
        cleaning_config={
            "negative": "keep_separately",
            "missing": "unknown_not_zero",
            "target": "positive_flow",
            "duplicate": "no_unproven_deletion",
            "unmatched_master": "quarantined",
        },
    )
    rows = checked["monthly"]
    aliases = {}
    for r in rows:
        if r["product_id"] in aliases and aliases[r["product_id"]] != r["unit_alias"]:
            raise BusinessError("Mã nghiên cứu ánh xạ không nhất quán.")
        aliases[r["product_id"]] = r["unit_alias"]
    if (
        len(rows) != survey["observed_unit_months"]
        or len(aliases) != survey["unique_retained_product_ids"]
    ):
        raise BusinessError("Số dòng dữ liệu đã lọc không khớp báo cáo chất lượng.")
    ForecastUnit.objects.bulk_create(
        [
            ForecastUnit(
                dataset_version=dataset,
                external_key=pid,
                label=alias,
                granularity="SKU",
                unit="đơn vị nguồn",
                scope_key="ALL_SOURCE_SITES_CHANNELS",
                mapping_status="UNVERIFIED",
            )
            for pid, alias in sorted(aliases.items())
        ],
        batch_size=1500,
    )
    units = {u.external_key: u for u in dataset.forecast_units.all()}
    ExternalSkuMap.objects.bulk_create(
        [
            ExternalSkuMap(
                forecast_unit=u,
                external_product_id=pid,
                evidence="Giữ nguyên khóa product_id của nguồn; chưa ánh xạ sản phẩm vận hành.",
            )
            for pid, u in units.items()
        ],
        batch_size=1500,
    )
    monthly = []
    seen = set()
    source_rows = 0
    for r in rows:
        m = month_parse(r["month"])
        key = (r["product_id"], m)
        if key in seen:
            raise BusinessError("Trùng khóa mã hàng và tháng trong dữ liệu đã lọc.")
        seen.add(key)
        pos, neg, net = (Decimal(r[k]) for k in ["positive_qty", "negative_qty_abs", "net_qty"])
        if (
            not all(v.is_finite() for v in [pos, neg, net])
            or pos < 0
            or neg < 0
            or pos - neg != net
        ):
            raise BusinessError("Số lượng tháng không hợp lệ.")
        n = int(r["source_rows"])
        source_rows += n
        monthly.append(
            MonthlySales(
                forecast_unit=units[r["product_id"]],
                month=m,
                positive_qty=pos,
                negative_qty_abs=neg,
                net_qty=net,
                target_qty=pos,
                observation_status="OBSERVED",
                source_row_count=n,
            )
        )
    if source_rows != survey["counts"]["retained_rows"]:
        raise BusinessError("Không đối soát được tổng số dòng nguồn.")
    MonthlySales.objects.bulk_create(monthly, batch_size=1500)
    counts = {r["file"]: r["rows"] for r in survey["files"]}
    sources = checked["sources"]
    SourceFile.objects.bulk_create(
        [
            SourceFile(
                dataset_version=dataset,
                relative_name=r["file"].replace("\\", "/"),
                sha256=r["sha256"],
                row_count=(
                    survey["master_rows"]
                    if r["file"].endswith("Productmaster.xlsx")
                    else counts[r["file"].replace("\\", "/").split("/")[-1]]
                ),
                schema_version="snapshot-v1",
                validation_status="VALID",
            )
            for r in sources
        ]
    )
    experiment = Experiment.objects.create(
        dataset_version=dataset,
        status="SUCCEEDED",
        target_definition={"target": "positive_flow", "unit": "source_product_id"},
        eligibility_policy={
            "min_valid_training_pairs": 6,
            "three_consecutive_calendar_lags": True,
        },
        split_config={**selected["split"], "scheme": "rolling_origin"},
        feature_spec={"columns": ["lag1", "lag2", "lag3", "ma3", "month_number"]},
        model_configs={
            "selected_before_test": selected["winner"],
            "random_forest": selected["rf_config"],
            "rf_fixed": selected["rf_fixed"],
            "artifact_hashes": checked["artifact_hashes"],
            "bundle_validation": "v2",
        },
    )
    validation = {r["method"]: r for r in summary["validation_metrics"]}
    final_metrics = {r["method"]: r for r in summary["test_metrics"]}
    model_results = {}
    for method in ["naive", "ma3", "linear", "random_forest"]:
        model_results[method] = ModelResult.objects.create(
            experiment=experiment,
            method=method,
            selected_on_validation=method == selected["winner"],
            validation_metrics=validation[method],
            test_metrics=final_metrics[method],
            scored_pair_manifest={
                "validation_n": checked["pair_counts"]["validation"],
                "test_n": checked["pair_counts"]["test"],
                "files": ["du_doan_kiem_dinh.csv", "du_doan_kiem_tra.csv"],
            },
        )
    run = ForecastRun.objects.create(
        model_result=model_results[selected["winner"]],
        cutoff_month=checked["cutoff"],
        target_month=checked["target"],
        scope_key="ALL_SOURCE_SITES_CHANNELS",
    )
    future_rows = checked["future"]
    values = []
    for r in future_rows:
        forecast = Decimal(r["forecast"])
        values.append(
            ForecastValue(
                run=run,
                forecast_unit=units[r["product_id"]],
                raw_value=forecast,
                nonnegative_value=forecast,
                result_status="VALID",
            )
        )
    ForecastValue.objects.bulk_create(values, batch_size=1500)
    run.status = "SUCCEEDED"
    run.completed_at = timezone.now()
    run.save()
    dataset.status = "VALIDATED"
    dataset.save()
    audit(
        actor,
        "IMPORT_RESEARCH",
        dataset,
        {"monthly_rows": len(rows), "source_rows": source_rows, "forecasts": len(values)},
    )
    return dataset


def suggestion_reasons(value):
    u = value.forecast_unit
    run = value.run
    dataset = run.model_result.experiment.dataset_version
    now_month = timezone.localdate().replace(day=1)
    reasons = []
    if dataset.source_type != SourceType.OPERATIONAL:
        reasons.append("Nguồn hiện tại chưa đủ điều kiện ghép với tồn cửa hàng.")
    if (
        dataset.status != "VALIDATED"
        or run.status != "SUCCEEDED"
        or run.model_result.experiment.status != "SUCCEEDED"
        or not run.model_result.selected_on_validation
        or value.result_status != "VALID"
        or value.nonnegative_value is None
        or not value.nonnegative_value.is_finite()
        or value.nonnegative_value < 0
    ):
        reasons.append("Chưa có kết quả dự báo hoàn tất và hợp lệ.")
    if (
        u.dataset_version_id != dataset.pk
        or u.scope_key != run.scope_key
        or run.scope_key != "STORE_MAIN"
    ):
        reasons.append("Phạm vi dự báo và cửa hàng không khớp.")
    if (
        u.granularity != "PRODUCT"
        or u.mapping_status != "VERIFIED"
        or u.internal_product_id is None
    ):
        reasons.append("Chưa xác minh ánh xạ ở cấp sản phẩm.")
    if (
        run.target_month != now_month
        or run.cutoff_month != month_add(now_month, -1)
        or dataset.coverage_end != run.cutoff_month
    ):
        reasons.append("Kỳ dự báo không phù hợp với tháng vận hành hiện tại.")
    if u.internal_product_id and (
        u.unit != u.internal_product.unit or not u.internal_product.is_active
    ):
        reasons.append("Đơn vị hoặc tình trạng sản phẩm chưa phù hợp.")
    if u.internal_product_id and not sellable_variants(u.internal_product_id).exists():
        reasons.append("Sản phẩm chưa có biến thể đang mở bán với thuộc tính và giá hợp lệ.")
    if (
        u.internal_product_id
        and not ReplenishmentPolicy.objects.filter(
            product=u.internal_product, effective_to__isnull=True
        ).exists()
    ):
        reasons.append("Chưa cấu hình tồn an toàn cho sản phẩm.")
    return reasons


def sellable_variants(product_id=None):
    query = Variant.objects.filter(
        is_active=True,
        product__is_active=True,
        product__category__is_active=True,
        product__brand__is_active=True,
        size__is_active=True,
        color__is_active=True,
        selling_price__gt=0,
    )
    return query.filter(product_id=product_id) if product_id is not None else query


def forecast_coverage(run):
    dataset = run.model_result.experiment.dataset_version
    raw = run.model_result.experiment.split_config.get("test", [])
    labels = re.findall(r"\d{4}-\d{2}", str(raw))
    coverage = {
        "forecasted": run.values.filter(
            result_status="VALID", nonnegative_value__isnull=False
        ).count(),
        "total_units": dataset.forecast_units.count(),
    }
    if labels:
        months = sorted(month_parse(label) for label in labels)
        observed = MonthlySales.objects.filter(
            forecast_unit__dataset_version=dataset,
            month__gte=months[0],
            month__lte=months[-1],
            target_qty__isnull=False,
        ).count()
        scored = run.model_result.test_metrics.get("n", 0)
        coverage.update(
            scored=scored, observed=observed, percent=100 * scored / observed if observed else None
        )
    return coverage


@transaction.atomic
def create_suggestion(actor, value_id):
    actor = authorize(actor, [Role.ADMIN], lock=True)
    value = (
        ForecastValue.objects.select_for_update(
            of=(
                "self",
                "forecast_unit",
                "run",
                "run__model_result",
                "run__model_result__experiment",
                "run__model_result__experiment__dataset_version",
            )
        )
        .select_related(
            "forecast_unit__internal_product", "run__model_result__experiment__dataset_version"
        )
        .get(pk=value_id)
    )
    reasons = suggestion_reasons(value)
    if reasons:
        raise BusinessError(" ".join(reasons))
    product = Product.objects.select_for_update().get(pk=value.forecast_unit.internal_product_id)
    value.forecast_unit.internal_product = product
    variants, balances = _lock_stock(
        list(product.variants.values_list("pk", flat=True)), active=False
    )
    policy = (
        ReplenishmentPolicy.objects.select_for_update()
        .filter(product=product, effective_to__isnull=True)
        .first()
    )
    if policy is None:
        raise BusinessError("Chưa cấu hình tồn an toàn.")
    reasons = suggestion_reasons(value)
    if reasons:
        raise BusinessError(" ".join(reasons))
    eligible = set(sellable_variants(product.pk).values_list("pk", flat=True))
    if not eligible:
        raise BusinessError("Không còn biến thể đang mở bán. Vui lòng kiểm tra lại sản phẩm.")
    stock = sum(b.quantity for key, b in balances.items() if key in eligible)
    period_start = timezone.make_aware(datetime.combine(value.run.target_month, time.min))
    period_end = timezone.make_aware(
        datetime.combine(month_add(value.run.target_month, 1), time.min)
    )
    period_sales = (
        SaleLine.objects.filter(
            variant__product=product,
            sale__status=Status.POSTED,
            sale__posted_at__gte=period_start,
            sale__posted_at__lt=period_end,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    remaining = max(Decimal(0), value.nonnegative_value - period_sales)
    q = max(
        0,
        int(
            (remaining + policy.safety_stock_qty - stock).to_integral_value(rounding=ROUND_CEILING)
        ),
    )
    if stock > 2_147_483_647 or q > 2_147_483_647:
        raise BusinessError(
            "Tồn hoặc lượng đề xuất vượt giới hạn cho phép. Cần đối chiếu lại dữ liệu."
        )
    obj = ReplenishmentSuggestion.objects.create(
        forecast_value=value,
        product=product,
        inventory_qty_snapshot=stock,
        inventory_versions={
            "balances": {str(k): b.version for k, b in balances.items()},
            "policy": policy.pk,
            "sellable_variants": sorted(eligible),
            "forecast": str(value.nonnegative_value),
            "period_sales_qty": period_sales,
            "remaining_forecast": str(remaining),
            "calculation_version": 2,
        },
        inventory_as_of=timezone.now(),
        safety_stock_snapshot=policy.safety_stock_qty,
        suggested_qty=q,
        status="CURRENT",
        generated_by=actor,
    )
    audit(
        actor,
        "CREATE_SUGGESTION",
        obj,
        {"quantity": q, "stock_snapshot": stock, "policy": policy.pk},
    )
    return obj


def suggestion_stale(suggestion):
    current = {
        str(v): n
        for v, n in StockBalance.objects.filter(variant__product=suggestion.product).values_list(
            "variant_id", "version"
        )
    }
    policy = ReplenishmentPolicy.objects.filter(
        product=suggestion.product, effective_to__isnull=True
    ).first()
    return (
        suggestion.status != "CURRENT"
        or current != suggestion.inventory_versions.get("balances")
        or policy is None
        or policy.pk != suggestion.inventory_versions.get("policy")
        or policy.safety_stock_qty != suggestion.safety_stock_snapshot
        or suggestion.product_id != suggestion.forecast_value.forecast_unit.internal_product_id
        or bool(suggestion_reasons(suggestion.forecast_value))
        or sorted(sellable_variants(suggestion.product_id).values_list("pk", flat=True))
        != suggestion.inventory_versions.get("sellable_variants")
        or str(suggestion.forecast_value.nonnegative_value)
        != suggestion.inventory_versions.get("forecast")
        or suggestion.inventory_versions.get("calculation_version") != 2
    )


def suggestion_preview(value):
    """Read-only estimate. Saving always recalculates with the existing stock locks."""
    if suggestion_reasons(value):
        return None
    product = value.forecast_unit.internal_product
    policy = ReplenishmentPolicy.objects.filter(product=product, effective_to__isnull=True).first()
    if policy is None:
        return None
    stock = (
        StockBalance.objects.filter(variant__in=sellable_variants(product.pk)).aggregate(
            total=Sum("quantity")
        )["total"]
        or 0
    )
    start = timezone.make_aware(datetime.combine(value.run.target_month, time.min))
    end = timezone.make_aware(datetime.combine(month_add(value.run.target_month, 1), time.min))
    sold = (
        SaleLine.objects.filter(
            variant__product=product,
            sale__status=Status.POSTED,
            sale__posted_at__gte=start,
            sale__posted_at__lt=end,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    remaining = max(Decimal(0), value.nonnegative_value - sold)
    quantity = max(
        0,
        int(
            (remaining + policy.safety_stock_qty - stock).to_integral_value(rounding=ROUND_CEILING)
        ),
    )
    return {
        "forecast": value.nonnegative_value,
        "sold": sold,
        "remaining": remaining,
        "stock": stock,
        "safety": policy.safety_stock_qty,
        "quantity": quantity,
        "within_limit": stock <= 2_147_483_647 and quantity <= 2_147_483_647,
    }


def evaluate_matrix(matrix, months):
    """Đánh giá theo thứ tự tháng và chốt phương pháp bằng tập kiểm định."""
    import numpy as np
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import LinearRegression

    try:
        a = np.asarray(matrix, dtype=float)
    except (TypeError, ValueError):
        raise BusinessError("Ma trận lịch sử phải là bảng số hai chiều.") from None
    if a.ndim != 2 or not a.shape[0] or not a.shape[1]:
        raise BusinessError("Ma trận lịch sử phải có sản phẩm và tháng quan sát.")
    n, length = a.shape
    if np.isinf(a).any() or (a[np.isfinite(a)] < 0).any():
        raise BusinessError(
            "Biến đích không được âm hoặc vô hạn. Dữ liệu thiếu giữ nguyên trạng thái chưa quan sát."
        )
    if (
        not isinstance(months, (list, tuple))
        or len(months) != length
        or any(type(m) is not date or m.day != 1 for m in months)
        or any(m != month_add(months[0], i) for i, m in enumerate(months))
    ):
        raise BusinessError(
            "Lịch tháng của tập thực nghiệm không liên tục hoặc không khớp ma trận."
        )
    if length < 16:
        raise BusinessError(
            "Cần ít nhất 16 tháng đóng kỳ để có 6 cặp huấn luyện, 3 tháng kiểm định và 4 tháng kiểm tra."
        )
    if (a[np.isfinite(a)] >= 1e14).any():
        raise BusinessError("Lượng bán vượt giới hạn lưu trữ của dữ liệu dự báo.")

    def features(t):
        lag = a[:, [t - 1, t - 2, t - 3]]
        return np.column_stack([lag, lag.mean(axis=1), np.full(n, t)])

    def context(t):
        x, y, ids = [], [], []
        for s in range(3, t):
            xx = features(s)
            mask = np.isfinite(xx).all(axis=1) & np.isfinite(a[:, s])
            x.append(xx[mask])
            y.append(a[mask, s])
            ids.append(np.where(mask)[0])
        X = np.concatenate(x)
        Y = np.concatenate(y)
        I = np.concatenate(ids)
        eligible = np.bincount(I, minlength=n) >= 6
        fit = eligible[I]
        xx = features(t)
        idx = np.where(eligible & np.isfinite(xx).all(axis=1))[0]
        return X[fit], Y[fit], xx[idx], idx

    month_numbers = [m.month for m in months] + [month_add(months[-1], 1).month]

    def predict(t):
        X, Y, xx, idx = context(t)
        if len(idx) == 0 or len(Y) == 0:
            return idx, {k: np.array([]) for k in ["naive", "ma3", "linear", "random_forest"]}
        # Đổi chỉ số đặc trưng sang tháng lịch trước khi huấn luyện.
        X[:, 4] = np.asarray([month_numbers[int(i)] for i in X[:, 4]])
        xx[:, 4] = month_numbers[t]
        lr = LinearRegression().fit(X, Y)
        rf = RandomForestRegressor(
            n_estimators=200, max_depth=5, min_samples_leaf=2, random_state=42, n_jobs=2
        ).fit(X, Y)
        linear_raw = lr.predict(xx)
        predictions = {
            "naive": xx[:, 0],
            "ma3": xx[:, 3],
            "linear_raw": linear_raw,
            "linear": np.maximum(0, linear_raw),
            "random_forest": np.maximum(0, rf.predict(xx)),
        }
        if any(not np.isfinite(v).all() for v in predictions.values()):
            raise BusinessError("Mô hình sinh kết quả không hữu hạn; chưa công bố dự báo.")
        return idx, predictions

    def score(truth, preds):
        truth = np.asarray(truth)
        preds = np.asarray(preds)
        diff = preds - truth
        if not len(truth):
            return {
                "n": 0,
                "mae": None,
                "rmse": None,
                "mape_positive_pct": None,
                "n_positive_actual": 0,
                "n_zero_actual": 0,
            }
        positive = truth > 0
        return {
            "n": len(truth),
            "mae": float(np.abs(diff).mean()),
            "rmse": float(np.sqrt(np.square(diff).mean())),
            "mape_positive_pct": (
                float((np.abs(diff[positive]) / truth[positive]).mean() * 100)
                if positive.any()
                else None
            ),
            "n_positive_actual": int(positive.sum()),
            "n_zero_actual": int((truth == 0).sum()),
        }

    results = {}
    selected = None
    for phase, origins in [
        ("validation", range(length - 7, length - 4)),
        ("test", range(length - 4, length)),
    ]:
        truth = []
        pred = {k: [] for k in ["naive", "ma3", "linear", "random_forest"]}
        for t in origins:
            idx, predictions = predict(t)
            valid = np.isfinite(a[idx, t])
            truth.extend(a[idx, t][valid])
            for k in pred:
                pred[k].extend(predictions[k][valid])
        if phase == "test" and not truth:
            raise BusinessError(
                "Không có cặp quan sát hợp lệ trong tập kiểm tra; chưa công bố kết quả."
            )
        results[phase] = {k: score(truth, v) for k, v in pred.items()}
        if phase == "validation":
            available = [k for k, v in results[phase].items() if v["n"] and v["mae"] is not None]
            if not available:
                raise BusinessError(
                    "Không có cặp kiểm định đủ điều kiện; chưa chọn được phương pháp."
                )
            selected = min(available, key=lambda k: results[phase][k]["mae"])
    idx, future = predict(length)
    if not len(idx):
        raise BusinessError("Không có sản phẩm đủ lịch sử liên tiếp để dự báo tháng tiếp theo.")
    results["selected"] = selected
    results["future"] = {int(i): float(y) for i, y in zip(idx, future[selected])}
    raw = future["linear_raw"] if selected == "linear" else future[selected]
    results["future_raw"] = {int(i): float(y) for i, y in zip(idx, raw)}
    return results
