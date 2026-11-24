"""Independent rerun of frozen recipes. Never overwrite the frozen experiment."""

import csv
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

R = Path(__file__).resolve().parent
A = R.parent / "web"
sys.path.insert(0, str(A))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from store.forecast.metrics import point_metrics, training_scale
from store.forecast.replenishment import month_add
from store.forecast.research import METHODS, predict_origin

OUT = R / "ket_qua_chay_lai"
OUT.mkdir(parents=True, exist_ok=True)


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


selection = json.loads(
    (R.parents[1] / "Du_lieu/Ket_qua/Random_Forest/selection_before_test.json").read_text(
        encoding="utf-8"
    )
)
monthly = R.parents[1] / "Du_lieu/Ket_qua/Goc/luong_ban_theo_thang.csv"
assert hashlib.sha256(monthly.read_bytes()).hexdigest() == selection["source_monthly_sha256"]
source = read(monthly)
keys = sorted({row["product_id"] for row in source})
positions = {key: i for i, key in enumerate(keys)}
months = [month_add(date(2022, 1, 1), i) for i in range(19)]
calendar = {month.strftime("%Y-%m"): i for i, month in enumerate(months)}
matrix = np.full((len(keys), 19), np.nan)
histories = defaultdict(list)
for row in source:
    month = date.fromisoformat(row["month"] + "-01")
    q = float(row["positive_qty"])
    matrix[positions[row["product_id"]], calendar[row["month"]]] = q
    histories[row["product_id"]].append((month, q))
actual = []
preds = {m: [] for m in METHODS}
scales = []
validation = {m: [] for m in METHODS}
val_actual = []
future = {
    row["product_id"]: row
    for row in read(R.parents[1] / "Du_lieu/Ket_qua/Random_Forest/future_predictions.csv")
}
reference = {
    (row["product_id"], row["month"]): row
    for row in read(R.parents[1] / "Du_lieu/Ket_qua/Random_Forest/test_predictions.csv")
}
matched = 0
origins = []
tick = time.monotonic()
csv_rows = []
for t in range(12, 20):
    target = month_add(months[0], t)
    ids, raw, training_n = predict_origin(
        matrix[:, :t].copy(),
        months[:t],
        {"n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2},
        42,
        recipes=selection["recipe_winners"],
    )
    values = {m: np.maximum(raw[m], 0) for m in METHODS}
    scored = 0
    for index, i in enumerate(ids):
        pid = keys[int(i)]
        label = target.strftime("%Y-%m")
        y = matrix[i, t] if t < 19 else np.nan
        csv_rows.append(
            {
                "product_id": pid,
                "month": label,
                "actual": float(y) if np.isfinite(y) else "",
                **{m: float(values[m][index]) for m in METHODS},
            }
        )
        if t == 19:
            assert pid in future
            for m in METHODS:
                assert abs(float(values[m][index]) - float(future[pid][m])) < 1e-8
        elif np.isfinite(y):
            scored += 1
            if t < 15:
                val_actual.append(float(y))
                for m in METHODS:
                    validation[m].append(float(values[m][index]))
            else:
                key = (pid, label)
                assert key in reference
                for m in METHODS:
                    assert abs(float(values[m][index]) - float(reference[key][m])) < 1e-8, (key, m)
                    preds[m].append(float(values[m][index]))
                    matched += 1
                actual.append(float(y))
                scales.append(training_scale(histories[pid], target))
    origins.append(
        {
            "target": str(target),
            "training_pairs": training_n,
            "candidate_skus": len(ids),
            "scored_pairs": scored,
        }
    )
    print(json.dumps(origins[-1]), flush=True)
val_scores = {m: point_metrics(val_actual, validation[m]) for m in METHODS}
test_scores = {m: point_metrics(actual, preds[m], scales) for m in METHODS}
for method in METHODS:
    saved = selection["validation_scores"][selection["recipe_winners"][method]["id"]]
    for metric in ["mae", "rmse", "mape_positive_pct"]:
        assert abs(val_scores[method][metric] - saved[metric]) < 1e-8
assert min(METHODS, key=lambda m: val_scores[m]["mae"]) == selection["selected_method"]
assert len(actual) == 7955 and len(val_actual) == 4561 and matched == 31820
with (OUT / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
    writer.writeheader()
    writer.writerows(csv_rows)
result = {
    "passed": True,
    "at": datetime.now(timezone.utc).isoformat(),
    "frozen_selection_unchanged": True,
    "source_monthly_sha256": selection["source_monthly_sha256"],
    "selected_method": selection["selected_method"],
    "validation_pairs": len(val_actual),
    "test_pairs": len(actual),
    "matched_test_predictions": matched,
    "matched_future_skus": len(future),
    "numeric_tolerance": 1e-8,
    "validation_metrics": val_scores,
    "test_metrics": test_scores,
    "origins": origins,
    "seconds": time.monotonic() - tick,
    "conclusion": "Reproducible implementation; exploratory Test period previously inspected; not evidence of 70-80% accuracy.",
}
(OUT / "verification.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result), flush=True)
