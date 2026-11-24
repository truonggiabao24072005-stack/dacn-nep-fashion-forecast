"""Thực nghiệm hồi cứu độc lập; không phải ứng dụng Web vận hành."""

import hashlib
import json
import math
import os
import platform
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

R = Path(__file__).resolve().parent

os.environ["MPLCONFIGDIR"] = str(R.parent / "web/.runtime/matplotlib")
import joblib
import matplotlib
import numpy as np
import openpyxl
import pandas as pd
import scipy
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression

ROOT = R.parents[1] / "Du_lieu/Nguon"
OUT = R / "ket_qua_chay_lai/goc"
OUT.mkdir(parents=True, exist_ok=True)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
now = lambda: datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat()


def write(name, x):
    (OUT / name).write_text(
        json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def emit(x):
    print(json.dumps(x, ensure_ascii=False, default=str), flush=True)


started = now()
start = time.perf_counter()
manifest = []


def row_source(p):
    manifest.append({"file": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": sha(p)})
    w = openpyxl.load_workbook(p, read_only=True, data_only=True)
    it = iter(w.active.values)
    head = next(it)
    return w, {v: i for i, v in enumerate(head)}, it


master = {}
styles = defaultdict(set)
counts = Counter()
w, h, it = row_source(ROOT / "MasterData/Productmaster.xlsx")
for row in it:
    if not any(v is not None for v in row):
        continue
    pid = row[h["product_id"]]
    assert pid not in master, "Trùng mã danh mục"
    master[pid] = {"product_group": row[h["product_group"]], "style": row[h["product_syle"]]}
    styles[row[h["product_syle"]]].add(pid)
w.close()
emit(
    {
        "master_rows": len(master),
        "styles_with_multiple_ids": sum(len(v) > 1 for v in styles.values()),
    }
)

aggregates = defaultdict(lambda: [0.0, 0.0, 0])
files = []
sites = set()
channels = Counter()
months = Counter()
for p in sorted((ROOT / "Sales_snapshot_data").glob("*.xlsx")):
    w, h, it = row_source(p)
    c = Counter()
    for row in it:
        if not any(v is not None for v in row):
            continue
        c["rows"] += 1
        counts["source_rows"] += 1
        pid = row[h["product_id"]]
        rawmo = row[h["month"]]
        q = row[h["sold_quantity"]]
        sites.add(str(row[h["site"]]))
        channels[str(row[h["channel_id"]])] += 1
        try:
            code = int(rawmo)
            yr, mo = divmod(code, 1000)
            if float(rawmo) != code or yr not in [2022, 2023] or not 1 <= mo <= 12:
                raise ValueError()
            idx = (yr - 2022) * 12 + mo - 1
            if idx > 18:
                raise ValueError()
        except (TypeError, ValueError):
            c["invalid_month_rows"] += 1
            continue
        if isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q):
            c["invalid_quantity_rows"] += 1
            continue
        months[f"{yr:04}-{mo:02}"] += 1
        c["negative_rows" if q < 0 else "zero_rows" if q == 0 else "positive_rows"] += 1
        if pid not in master:
            c["unmatched_master_rows"] += 1
            continue
        a = aggregates[(str(pid), idx)]
        a[0] += max(float(q), 0.0)
        a[1] += max(-float(q), 0.0)
        a[2] += 1
        c["retained_rows"] += 1
    w.close()
    files.append({"file": p.name, **dict(c)})
    counts.update({k: v for k, v in c.items() if k != "rows"})
    emit(files[-1])

pids = sorted({p for p, t in aggregates})
pi = {p: i for i, p in enumerate(pids)}
aliases = {p: f"MH{i+1:05}" for i, p in enumerate(pids)}
y = np.full((len(pids), 19), np.nan)
rows = []
for (p, t), (pos, neg, n) in sorted(aggregates.items()):
    y[pi[p], t] = pos
    rows.append(
        {
            "unit_alias": aliases[p],
            "product_id": p,
            "month": f"{2022+t//12:04}-{t%12+1:02}",
            "positive_qty": pos,
            "negative_qty_abs": neg,
            "net_qty": pos - neg,
            "source_rows": int(n),
            "product_group": master[p]["product_group"],
        }
    )
monthly = pd.DataFrame(rows)
monthly.to_csv(OUT / "luong_ban_theo_thang.csv", index=False, encoding="utf-8-sig")
write("source_manifest.json", manifest)
write(
    "khao_sat_du_lieu.json",
    {
        "started_at": started,
        "finished_at": now(),
        "counts": dict(counts),
        "files": files,
        "master_rows": len(master),
        "master_style_groups_with_multiple_ids": sum(len(v) > 1 for v in styles.values()),
        "unique_retained_product_ids": len(pids),
        "unique_sites": len(sites),
        "raw_channel_counts": dict(channels),
        "observed_unit_months": len(monthly),
        "grid_cells": int(y.size),
        "unknown_unit_months": int(np.isnan(y).sum()),
        "zero_positive_flow_months": int(np.sum(y == 0)),
        "target_definition": "Sum of recorded positive sold_quantity within source product_id and month",
        "scope": "All sites and channels represented in the 19 supplied sales files; not one operational store",
        "negative_policy": "Preserved separately, not asserted to be returns; positive-flow target is exploratory",
        "missing_policy": "Unknown months remain NA; no automatic zero filling",
        "duplicate_policy": "No deletion of same-looking rows without transaction identity",
        "ingestion_seconds": time.perf_counter() - start,
    },
)

FEATURES = ["lag1", "lag2", "lag3", "ma3", "month_number"]


def feature_at(a, t):
    lag = a[:, [t - 1, t - 2, t - 3]]
    return np.column_stack([lag, np.mean(lag, axis=1), np.full(len(a), t % 12 + 1)])


def context(a, t):
    xs = []
    ys = []
    ids = []
    for s in range(3, t):
        xx = feature_at(a, s)
        yy = a[:, s]
        ok = np.isfinite(xx).all(axis=1) & np.isfinite(yy)
        xs.append(xx[ok])
        ys.append(yy[ok])
        ids.append(np.where(ok)[0])
    X = np.concatenate(xs)
    Y = np.concatenate(ys)
    I = np.concatenate(ids)
    cnt = np.bincount(I, minlength=len(a))
    eligible = cnt >= 6
    fitmask = eligible[I]
    nextx = feature_at(a, t)
    candidate = eligible & np.isfinite(nextx).all(axis=1)
    idx = np.where(candidate)[0]
    actual = a[idx, t] if t < a.shape[1] else np.full(len(idx), np.nan)
    return X[fitmask], Y[fitmask], nextx[idx], idx, actual, int(eligible.sum())


def metrics(actual, pred):
    ok = np.isfinite(actual) & np.isfinite(pred)
    a = actual[ok]
    p = pred[ok]
    assert len(a) > 0
    e = a - p
    pos = a > 0
    return {
        "n": int(len(a)),
        "n_positive_actual": int(pos.sum()),
        "n_zero_actual": int((a == 0).sum()),
        "mae": float(np.mean(np.abs(e))),
        "rmse": float(np.sqrt(np.mean(e * e))),
        "mape_positive_pct": float(np.mean(np.abs(e[pos]) / a[pos]) * 100) if pos.any() else None,
        "mape_positive_coverage_pct": float(pos.mean() * 100),
    }


grid = [
    {"max_depth": depth, "min_samples_leaf": leaf} for depth in [5, 10, None] for leaf in [2, 5]
]
base_rf = {
    "n_estimators": 200,
    "random_state": 42,
    "n_jobs": 2,
    "max_features": 1.0,
    "bootstrap": True,
}
validation = []
grid_preds = defaultdict(list)
contexts = []
for t in [12, 13, 14]:
    X, Y, XX, idx, a, ne = context(y, t)
    assert X.size and XX.size
    lr = LinearRegression(fit_intercept=True).fit(X, Y)
    raw = lr.predict(XX)
    frame = pd.DataFrame(
        {
            "unit_alias": [aliases[pids[i]] for i in idx],
            "product_id": [pids[i] for i in idx],
            "month": f"2023-{t-11:02}",
            "actual": a,
            "naive": XX[:, 0],
            "ma3": XX[:, 3],
            "linear_raw": raw,
            "linear": np.maximum(raw, 0),
        }
    )
    for j, cfg in enumerate(grid):
        tick = time.perf_counter()
        rf = RandomForestRegressor(**base_rf, **cfg).fit(X, Y)
        v = rf.predict(XX)
        frame[f"rf_{j}"] = v
        grid_preds[j].append((a, v))
        emit(
            {
                "validation_month": t - 11,
                "rf_config": j,
                "train_pairs": len(Y),
                "candidates": len(idx),
                "seconds": round(time.perf_counter() - tick, 2),
            }
        )
    validation.append(frame)
    contexts.append(
        {
            "phase": "validation",
            "month": frame.month.iloc[0],
            "train_pairs": len(Y),
            "eligible_units": ne,
            "candidate_units": len(idx),
            "scored_pairs": int(np.isfinite(a).sum()),
            "unknown_target_candidates": int(np.isnan(a).sum()),
            "observed_target_units": int(np.isfinite(y[:, t]).sum()),
        }
    )

v = pd.concat(validation, ignore_index=True)
grid_scores = []
for j, cfg in enumerate(grid):
    grid_scores.append(
        {"config_id": j, **cfg, **metrics(v.actual.to_numpy(), v[f"rf_{j}"].to_numpy())}
    )
best_rf = min(grid_scores, key=lambda r: (r["mae"], r["config_id"]))
best_j = best_rf["config_id"]
v["random_forest"] = v[f"rf_{best_j}"]
families = ["naive", "ma3", "linear", "random_forest"]
vs = [{"method": m, **metrics(v.actual.to_numpy(), v[m].to_numpy())} for m in families]
winner = min(vs, key=lambda a: (a["mae"], families.index(a["method"])))["method"]
pd.DataFrame(grid_scores).to_csv(
    OUT / "kiem_dinh_cau_hinh_rung.csv", index=False, encoding="utf-8-sig"
)
v.to_csv(OUT / "du_doan_kiem_dinh.csv", index=False, encoding="utf-8-sig")
selection = {
    "created_before_test_at": now(),
    "winner": winner,
    "rf_config": grid[best_j],
    "rf_fixed": base_rf,
    "validation_metrics": vs,
    "feature_order": FEATURES,
    "minimum_train_pairs_per_unit": 6,
    "seed": 42,
    "split": {
        "initial_train": "2022-01 through 2022-12",
        "validation": "2023-01 through 2023-03",
        "test": "2023-04 through 2023-07",
    },
    "target": "recorded positive flow",
    "granularity": "source product_id × month",
    "refit": "expanding past data at each origin",
    "selection": "pooled validation MAE; exact ties use naive, ma3, linear, random_forest order",
    "postprocess": "clip negative forecasts to zero, no rounding for scoring",
    "no_zero_imputation": True,
    "scope": "all represented sites and channels, pooled at source product_id",
}
write("lua_chon_truoc_kiem_tra.json", selection)
selection_hash = sha(OUT / "lua_chon_truoc_kiem_tra.json")
emit({"selected_on_validation": winner, "rf": grid[best_j], "validation_metrics": vs})

tests = []
for t in [15, 16, 17, 18]:
    tick = time.perf_counter()
    X, Y, XX, idx, a, ne = context(y, t)
    lr = LinearRegression(fit_intercept=True).fit(X, Y)
    raw = lr.predict(XX)
    rf = RandomForestRegressor(**base_rf, **grid[best_j]).fit(X, Y)
    frame = pd.DataFrame(
        {
            "unit_alias": [aliases[pids[i]] for i in idx],
            "product_id": [pids[i] for i in idx],
            "month": f"2023-{t-11:02}",
            "actual": a,
            "naive": XX[:, 0],
            "ma3": XX[:, 3],
            "linear_raw": raw,
            "linear": np.maximum(raw, 0),
            "random_forest": rf.predict(XX),
        }
    )
    tests.append(frame)
    contexts.append(
        {
            "phase": "test",
            "month": frame.month.iloc[0],
            "train_pairs": len(Y),
            "eligible_units": ne,
            "candidate_units": len(idx),
            "scored_pairs": int(np.isfinite(a).sum()),
            "unknown_target_candidates": int(np.isnan(a).sum()),
            "observed_target_units": int(np.isfinite(y[:, t]).sum()),
        }
    )
    emit(
        {
            "test_month": t - 11,
            "train_pairs": len(Y),
            "candidates": len(idx),
            "seconds": round(time.perf_counter() - tick, 2),
        }
    )

test = pd.concat(tests, ignore_index=True)
test.to_csv(OUT / "du_doan_kiem_tra.csv", index=False, encoding="utf-8-sig")
ts = [{"method": m, **metrics(test.actual.to_numpy(), test[m].to_numpy())} for m in families]
per_month = []
for mo, g in test.groupby("month", sort=True):
    per_month.extend(
        [
            {"month": mo, "method": m, **metrics(g.actual.to_numpy(), g[m].to_numpy())}
            for m in families
        ]
    )
pd.DataFrame(per_month).to_csv(OUT / "sai_so_theo_thang.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(contexts).to_csv(OUT / "muc_bao_phu.csv", index=False, encoding="utf-8-sig")
assert sha(OUT / "lua_chon_truoc_kiem_tra.json") == selection_hash

# A later month must not affect inputs, eligibility, or labels at an earlier origin.
perturbed = y.copy()
perturbed[:, 12:] = 999999
c1 = context(y, 12)
c2 = context(perturbed, 12)
leak_checks = [np.array_equal(c1[i], c2[i], equal_nan=True) for i in [0, 1, 2, 3]]
assert all(leak_checks)
m = metrics(np.array([0.0, 2.0]), np.array([1.0, 1.0]))
assert m["mae"] == 1 and m["rmse"] == 1 and m["mape_positive_pct"] == 50 and m["n_zero_actual"] == 1


def suggest(f, s, i, compatible=True):
    if not compatible:
        return {"status": "INCOMPATIBLE", "qty": None}
    if any(x is None for x in [f, s, i]):
        return {"status": "INCOMPLETE", "qty": None}
    if not all(math.isfinite(x) and x >= 0 for x in [f, s, i]):
        return {"status": "INVALID", "qty": None}
    return {"status": "OK", "qty": max(0, math.ceil(f + s - i))}


formula_cases = [
    ("CT01", 32.4, 5, 20, True, {"status": "OK", "qty": 18}),
    ("CT02", 10, 2, 15, True, {"status": "OK", "qty": 0}),
    ("CT03", None, 5, 20, True, {"status": "INCOMPLETE", "qty": None}),
    ("CT04", 32.4, 5, 20, False, {"status": "INCOMPATIBLE", "qty": None}),
    ("CT05", 12.4, 3, 10, True, {"status": "OK", "qty": 6}),
    ("CT06", float("inf"), 3, 10, True, {"status": "INVALID", "qty": None}),
]
formula_results = []
for code, f, s, i, compat, expected in formula_cases:
    actual = suggest(f, s, i, compat)
    assert actual == expected
    formula_results.append(
        {
            "code": code,
            "forecast": f if f is None or math.isfinite(f) else "Infinity",
            "safety": s,
            "inventory": i,
            "compatible": compat,
            "expected": expected,
            "actual": actual,
            "passed": True,
        }
    )
write(
    "kiem_tra_quy_trinh.json",
    {
        "future_perturbation_inputs_unchanged": all(leak_checks),
        "metric_zero_case_passed": True,
        "same_pairs_for_four_methods": True,
        "selection_hash_unchanged_after_test": True,
        "formula_unit_checks": formula_results,
        "web_tests_executed": False,
        "database_transaction_tests_executed": False,
        "note": "These are checks of research inputs and the formula function, not Web acceptance tests.",
    },
)

valid = test[np.isfinite(test.actual)].copy()
valid["abs_error"] = np.abs(valid.actual - valid[winner])
valid["signed_error"] = valid[winner] - valid.actual
worst = valid.sort_values(["abs_error", "unit_alias", "month"], ascending=[False, True, True]).head(
    3
)
worst.to_csv(OUT / "ba_truong_hop_sai_so_lon.csv", index=False, encoding="utf-8-sig")
macro = (
    valid.assign(ae=lambda a: np.abs(a.actual - a[winner])).groupby("product_id").ae.mean().mean()
)

# Produce a dated research forecast only; never combine it with 2026 stock.
X, Y, XX, idx, a, ne = context(y, 19)
if winner == "naive":
    future = XX[:, 0]
    model = None
elif winner == "ma3":
    future = XX[:, 3]
    model = None
elif winner == "linear":
    model = LinearRegression().fit(X, Y)
    future = np.maximum(model.predict(XX), 0)
else:
    model = RandomForestRegressor(**base_rf, **grid[best_j]).fit(X, Y)
    future = model.predict(XX)
future_frame = pd.DataFrame(
    {
        "unit_alias": [aliases[pids[i]] for i in idx],
        "product_id": [pids[i] for i in idx],
        "cutoff_month": "2023-07",
        "target_month": "2023-08",
        "method": winner,
        "forecast": future,
    }
)
future_frame.to_csv(OUT / "du_bao_nghien_cuu_2023_08.csv", index=False, encoding="utf-8-sig")
if model is not None:
    joblib.dump(model, OUT / "mo_hinh_nghien_cuu.joblib")

summary = {
    "run_started_at": started,
    "run_finished_at": now(),
    "elapsed_seconds": time.perf_counter() - start,
    "environment": {
        "python": platform.python_version(),
        "os": platform.system() + " " + platform.release(),
        "cpu_logical": os.cpu_count(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
        "openpyxl": openpyxl.__version__,
        "matplotlib": matplotlib.__version__,
    },
    "validation_metrics": vs,
    "test_metrics": ts,
    "selected_method": winner,
    "rf_selected_config": grid[best_j],
    "selected_method_macro_mae": float(macro),
    "selection_file_sha256": selection_hash,
    "test_unique_scored_units": int(valid.product_id.nunique()),
    "test_scored_pairs": len(valid),
    "test_candidate_pairs": len(test),
    "future_research_forecast_count": len(future_frame),
    "linear_negative_raw_validation": int((v.linear_raw < 0).sum()),
    "linear_negative_raw_test": int((test.linear_raw < 0).sum()),
    "worst_cases": worst[
        ["unit_alias", "product_id", "month", "actual", winner, "abs_error", "signed_error"]
    ].to_dict("records"),
}
write("tong_hop_thuc_nghiem.json", summary)
emit(summary)
