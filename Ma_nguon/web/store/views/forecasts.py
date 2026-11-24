from types import SimpleNamespace

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from store.forecast.replenishment import (
    create_suggestion,
    forecast_coverage,
    month_add,
    sellable_variants,
    suggestion_preview,
    suggestion_reasons,
    suggestion_stale,
)
from store.models import DatasetVersion, ForecastRun, ForecastValue, Role, models
from store.services.documents import BusinessError
from store.services.search import filter_queryset_text
from store.validation import positive_identifier
from store.views.common import role_required


@role_required(Role.ADMIN, Role.WAREHOUSE)
def forecasts(request):
    datasets = DatasetVersion.objects.filter(status="VALIDATED").order_by("-pk")
    identifier = positive_identifier(request.GET.get("dataset"))
    selected = (
        datasets.filter(pk=identifier).first() if identifier is not None else datasets.first()
    )
    values = ForecastValue.objects.none()
    models = []
    runs = []
    run = None
    coverage = {}
    if selected:
        runs = ForecastRun.objects.filter(
            model_result__experiment__dataset_version=selected, status="SUCCEEDED"
        ).order_by("-target_month", "-pk")
        run = runs.filter(model_result__selected_on_validation=True).first() or runs.first()
        if run:
            coverage = forecast_coverage(run)
            values = run.values.select_related("forecast_unit__internal_product").order_by(
                "forecast_unit__label"
            )
            if selected.source_type == "RESEARCH":
                values = values.filter(forecast_unit__internal_product__is_active=True)
            q = request.GET.get("q", "").strip()
            if q:
                values = filter_queryset_text(
                    values,
                    q,
                    (
                        "forecast_unit__label",
                        "forecast_unit__external_key",
                        "forecast_unit__internal_product__code",
                        "forecast_unit__internal_product__name",
                    ),
                )
            if request.user.role == Role.ADMIN:
                models = run.model_result.experiment.model_results.order_by("pk")
    return render(
        request,
        "store/forecast/list.html",
        {
            "title": "Dự báo và kế hoạch nhập",
            "datasets": datasets,
            "selected": selected,
            "run": run,
            "page": Paginator(values, 25).get_page(request.GET.get("page")),
            "models": models,
            "q": request.GET.get("q", ""),
            "coverage": coverage,
        },
    )


@role_required(Role.ADMIN, Role.WAREHOUSE)
def forecast_detail(request, pk):
    v = get_object_or_404(
        ForecastValue.objects.select_related(
            "forecast_unit__internal_product", "run__model_result__experiment__dataset_version"
        ),
        pk=pk,
    )
    reasons = suggestion_reasons(v)
    product = v.forecast_unit.internal_product
    suggestions = []
    for obj in v.suggestions.select_related(
        "product",
        "forecast_value__forecast_unit__internal_product",
        "forecast_value__run__model_result__experiment__dataset_version",
    ).order_by("-inventory_as_of", "-pk")[:10]:
        suggestions.append({"object": obj, "stale": suggestion_stale(obj)})
    dataset = v.forecast_unit.dataset_version
    end = min(dataset.coverage_end, v.run.cutoff_month)
    start = max(dataset.coverage_start, month_add(end, -23))
    observed = {
        row.month: row
        for row in v.forecast_unit.monthly_sales.filter(month__gte=start, month__lte=end)
    }
    history = []
    month = start
    while month <= end:
        history.append(
            observed.get(
                month,
                SimpleNamespace(
                    month=month,
                    target_qty=None,
                    negative_qty_abs=None,
                    observation_status="UNKNOWN",
                ),
            )
        )
        if month == end:
            break
        month = month_add(month, 1)
    chart = {
        "labels": [r.month.strftime("%m/%Y") for r in history],
        "values": [float(r.target_qty) if r.target_qty is not None else None for r in history],
    }
    return render(
        request,
        "store/forecast/detail.html",
        {
            "title": v.forecast_unit.label or v.forecast_unit.external_key,
            "value": v,
            "reasons": reasons,
            "product": product,
            "variants": (
                product.variants.select_related("size", "color", "balance") if product else []
            ),
            "suggestions": suggestions,
            "history": history,
            "chart": chart,
            "preview": suggestion_preview(v) if not reasons else None,
            "sellable_variant_ids": (
                set(sellable_variants(product.pk).values_list("pk", flat=True))
                if product
                else set()
            ),
        },
    )


@role_required(Role.ADMIN)
@require_POST
def suggest(request, pk):
    try:
        obj = create_suggestion(request.user, pk)
        messages.success(
            request,
            f"Đề xuất {obj.suggested_qty} {obj.product.unit}. Chưa tạo phiếu nhập hoặc đơn đặt hàng.",
        )
    except BusinessError as exc:
        messages.error(request, str(exc))
    except ObjectDoesNotExist:
        raise Http404
    return redirect("forecast_detail", pk=pk)
