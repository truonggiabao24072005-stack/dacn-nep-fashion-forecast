"""Read-only comparison of published research rows with the checked result bundle."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from audit_project import snapshot
from django.conf import settings

from store.forecast.replenishment import suggestion_reasons
from store.forecast.validation import read_bundle
from store.models import DatasetVersion, ForecastRun, MonthlySales, SourceType


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path, default=BASE / ".runtime/evidence/forecast_audit_20261025"
    )
    args = parser.parse_args()
    before = snapshot()
    checked = read_bundle(settings.RESEARCH_RESULTS_DIR)
    dataset = (
        DatasetVersion.objects.filter(source_type=SourceType.RESEARCH, status="VALIDATED")
        .order_by("-pk")
        .first()
    )
    assert dataset is not None
    rows = {(r["product_id"], r["month"]): r for r in checked["monthly"]}
    bad_monthly = 0
    stored = MonthlySales.objects.filter(forecast_unit__dataset_version=dataset).select_related(
        "forecast_unit"
    )
    assert stored.count() == len(rows)
    for row in stored.iterator(chunk_size=2000):
        key = (row.forecast_unit.external_key, row.month.strftime("%Y-%m"))
        source = rows.pop(key, None)
        if (
            source is None
            or any(
                getattr(row, key) != Decimal(source[key]).quantize(Decimal(".0001"))
                for key in ["positive_qty", "negative_qty_abs", "net_qty"]
            )
            or row.target_qty != row.positive_qty
            or row.source_row_count != int(source["source_rows"])
        ):
            bad_monthly += 1
    run = (
        ForecastRun.objects.filter(
            model_result__experiment__dataset_version=dataset, status="SUCCEEDED"
        )
        .order_by("-pk")
        .first()
    )
    assert run and run.cutoff_month == checked["cutoff"] and run.target_month == checked["target"]
    assert run.model_result.method == checked["selection"]["winner"]
    for result in run.model_result.experiment.model_results.all():
        assert result.validation_metrics == checked["validation"][result.method]
        assert result.test_metrics == checked["test"][result.method]
    values = {
        row["product_id"]: Decimal(row["forecast"]).quantize(Decimal(".0001"))
        for row in checked["future"]
    }
    bad_forecasts = 0
    stored_forecasts = run.values.select_related("forecast_unit")
    assert stored_forecasts.count() == len(values)
    for row in stored_forecasts.iterator(chunk_size=1000):
        if (
            row.nonnegative_value != values.pop(row.forecast_unit.external_key, None)
            or row.result_status != "VALID"
        ):
            bad_forecasts += 1
    assert bad_monthly == bad_forecasts == 0 and not rows and not values
    assert suggestion_reasons(stored_forecasts.first())
    assert before == snapshot()
    result = {
        "at": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "business_data_unchanged": True,
        "monthly_rows_compared": stored.count(),
        "forecast_rows_compared": stored_forecasts.count(),
        "monthly_mismatches": bad_monthly,
        "forecast_mismatches": bad_forecasts,
        "models_compared": 4,
        "research_replenishment_blocked": True,
        "checked_bundle_sha256": checked["digest"],
        "published_dataset_code": dataset.code,
        "published_dataset_reimported": False,
        "artifact_hashes": checked["artifact_hashes"],
    }
    output = args.output_dir / "database.json"
    output.parent.mkdir(exist_ok=True, parents=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "artifact_hashes"}))


if __name__ == "__main__":
    main()
