import csv
from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse

from store.forecast.charts import comparison_rows, comparison_svg
from store.forecast.replenishment import month_add, month_parse
from store.forecast.research import (
    METHODS,
    generate_research,
    research_context,
    research_runs,
    stock_scenario,
)
from store.forms.research import DemandForecastForm, StockScenarioForm
from store.models import DatasetVersion, MonthlySales, Role, SourceType
from store.services.documents import BusinessError, audit
from store.validation import positive_identifier
from store.views.common import role_required


@role_required(Role.ADMIN, Role.WAREHOUSE)
def workspace(request):
    if request.method not in ["GET", "POST"]:
        return HttpResponse(status=405, headers={"Allow": "GET, POST"})
    if request.method == "POST" and request.user.role != Role.ADMIN:
        return HttpResponseForbidden("Quản trị viên chạy dự báo và tính tình huống.")
    datasets = DatasetVersion.objects.filter(
        source_type=SourceType.RESEARCH, status="VALIDATED"
    ).order_by("-pk")
    data = request.POST if request.method == "POST" else request.GET
    dataset_id = positive_identifier(data.get("dataset"))
    dataset = datasets.filter(pk=dataset_id).first() if dataset_id else datasets.first()
    targets = []
    models = {}
    selected = "naive"
    context_error = ""
    experiment = None
    if dataset:
        try:
            experiment, models, selected, targets = research_context(dataset)
        except BusinessError as exc:
            context_error = str(exc)
    initial_unit = (
        dataset.forecast_units.filter(internal_product__is_active=True).order_by("label").first()
        if dataset
        else None
    )
    params = {
        "dataset": dataset.pk if dataset else "",
        "experiment": experiment.pk if experiment else "",
        "target": targets[-1].strftime("%Y-%m") if targets else "",
        "unit": initial_unit.pk if initial_unit else "",
    }
    params.update({k: data[k] for k in ["dataset", "target", "unit"] if k in data})
    form = DemandForecastForm(params, datasets=datasets, dataset=dataset, targets=targets)
    scenario_form = StockScenarioForm(
        request.POST if request.method == "POST" and data.get("action") == "scenario" else None,
        initial={"method": selected, "sold": 0},
        prefix="scenario",
    )
    runs = {}
    predictions = []
    metrics = []
    history = []
    scenario = None
    actual = None
    target = None
    unit = None
    readiness = None
    if not context_error and form.is_valid():
        dataset = form.cleaned_data["dataset"]
        target = month_parse(form.cleaned_data["target"])
        unit = form.cleaned_data["unit"]
        if request.method == "POST" and data.get("action") == "run":
            try:
                result = generate_research(
                    request.user, dataset.pk, target, form.cleaned_data["experiment"].pk
                )
                messages.success(
                    request,
                    f"Đã cập nhật dự đoán nhu cầu tháng {target:%m/%Y} từ lịch sử đến hết {month_add(target,-1):%m/%Y}.",
                )
                return redirect(reverse("research_workspace") + "?" + urlencode(params))
            except (BusinessError, ObjectDoesNotExist) as exc:
                form.add_error(None, str(exc))
        runs, selected = research_runs(dataset, target, form.cleaned_data["experiment"].pk)
        # Scientific metrics remain in research artifacts, outside the shop workflow.
        actual_row = unit.monthly_sales.filter(month=target, target_qty__isnull=False).first()
        actual = actual_row.target_qty if actual_row else None
        for method in METHODS:
            run = runs.get(method)
            value = (
                run.values.filter(forecast_unit=unit, result_status="VALID").first()
                if run
                else None
            )
            predictions.append(
                {
                    "method": method,
                    "value": value,
                    "selected": method == selected,
                    "absolute_error": (
                        abs(value.nonnegative_value - actual)
                        if value and actual is not None
                        else None
                    ),
                }
            )
        cutoff = month_add(target, -1)
        observed = {r.month: r for r in unit.monthly_sales.filter(month__lte=cutoff)}
        month = dataset.coverage_start
        while month <= cutoff:
            history.append(
                observed.get(
                    month,
                    SimpleNamespace(month=month, target_qty=None, observation_status="UNKNOWN"),
                )
            )
            month = month_add(month, 1)
        quantities = [r.target_qty for r in history]
        pairs = sum(
            all(value is not None for value in quantities[t - 3 : t + 1])
            for t in range(3, len(quantities))
        )
        missing = [r.month.strftime("%m/%Y") for r in history[-3:] if r.target_qty is None]
        readiness = {
            "training_pairs": pairs,
            "missing_lags": missing,
            "eligible": pairs >= 6 and len(history) >= 3 and not missing,
        }
        if (
            request.method == "POST"
            and data.get("action") == "scenario"
            and scenario_form.is_valid()
        ):
            try:
                method = scenario_form.cleaned_data["method"]
                run = runs.get(method)
                value = run.values.get(forecast_unit=unit, result_status="VALID") if run else None
                if value is None:
                    raise BusinessError(
                        "Chạy Forecast cho kỳ và phương pháp trước khi tính tình huống."
                    )
                scenario = stock_scenario(
                    value,
                    scenario_form.cleaned_data["stock"],
                    scenario_form.cleaned_data["safety"],
                    scenario_form.cleaned_data["sold"],
                )
                audit(
                    request.user,
                    "RESEARCH_STOCK_SCENARIO",
                    value,
                    {k: str(v) for k, v in scenario.items()},
                    reason="Đầu vào tồn và tồn an toàn do người dùng giả định; không lưu đề xuất vận hành hoặc ghi kho.",
                )
            except (BusinessError, ObjectDoesNotExist) as exc:
                scenario_form.add_error(None, str(exc))
        if request.method == "GET" and data.get("export") == "csv":
            return export_comparison(dataset, target, runs)
    if request.method == "POST" and data.get("action") not in ["run", "scenario"]:
        form.add_error(None, "Thao tác không hợp lệ.")
    selected_prediction = next((row for row in predictions if row["selected"]), None)
    comparison = comparison_rows(unit, models[selected], target) if unit and target else []
    period_result = next((row for row in comparison if row["month"] == target), None)
    if request.method == "GET" and data.get("export") == "product" and unit and target:
        return export_product_comparison(unit, target, comparison)
    return render(
        request,
        "store/forecast/research.html",
        {
            "title": "Dự đoán nhu cầu sản phẩm",
            "form": form,
            "dataset": dataset,
            "experiment": experiment,
            "target": target,
            "unit": unit,
            "selected_prediction": selected_prediction,
            "comparison": comparison,
            "period_result": period_result,
            "published_run": runs.get(selected),
            "comparison_svg": comparison_svg(comparison) if comparison else "",
            "context_error": context_error,
            "runs": runs,
            "selected_method": selected,
            "predictions": predictions,
            "metrics": metrics,
            "actual": actual,
            "actual_known": actual is not None,
            "history": history,
            "scenario_form": scenario_form,
            "scenario": scenario,
            "query": urlencode(params),
            "readiness": readiness,
            "cutoff": month_add(target, -1) if target else None,
            "validation_end": month_add(targets[0], -1) if targets else None,
            "chart": {
                "labels": [r.month.strftime("%m/%Y") for r in history],
                "values": [
                    float(r.target_qty) if r.target_qty is not None else None for r in history
                ],
            },
        },
    )


def export_product_comparison(unit, target, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="doi_chieu_nhu_cau_{target:%Y_%m}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Mã sản phẩm", "Tháng", "Dự đoán", "Thực tế", "Chênh lệch", "Đơn vị"])

    def text(value):
        return "'" + value if value and value[0] in "=+-@\t\r\n" else value

    for row in rows:
        writer.writerow([
            text(unit.label), row["month"].strftime("%Y-%m"),
            "" if row["forecast"] is None else row["forecast"],
            "" if row["actual"] is None else row["actual"],
            "" if row["difference"] is None else row["difference"], text(unit.unit),
        ])
    return response


def export_comparison(dataset, target, runs):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="research_forecast_{target:%Y_%m}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Source SKU",
            "Source product ID",
            "Target month",
            "Cutoff month",
            "Method",
            "Forecast",
            "Raw Forecast",
            "Actual",
            "Absolute Error",
            "Unit",
            "Source type",
            "Experiment ID",
        ]
    )
    units = list(dataset.forecast_units.filter(internal_product__is_active=True).order_by("label"))
    actual = dict(
        MonthlySales.objects.filter(forecast_unit__in=units, month=target).values_list(
            "forecast_unit_id", "target_qty"
        )
    )

    def safe(value):
        return "'" + value if value and value[0] in "=+-@\t\r\n" else value

    for method in METHODS:
        if method not in runs:
            continue
        for value in (
            runs[method]
            .values.filter(forecast_unit__in=units)
            .select_related("forecast_unit")
            .order_by("forecast_unit__label")
        ):
            truth = actual.get(value.forecast_unit_id)
            writer.writerow(
                [
                    safe(value.forecast_unit.label),
                    safe(value.forecast_unit.external_key),
                    str(target),
                    str(month_add(target, -1)),
                    method,
                    value.nonnegative_value,
                    value.raw_value,
                    "" if truth is None else truth,
                    "" if truth is None else abs(value.nonnegative_value - truth),
                    safe(value.forecast_unit.unit),
                    "RESEARCH",
                    runs[method].model_result.experiment_id,
                ]
            )
    return response
