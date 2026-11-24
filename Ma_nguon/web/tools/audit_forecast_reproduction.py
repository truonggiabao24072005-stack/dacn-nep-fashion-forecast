"""Independently refit saved research folds without replacing the original results."""

import argparse
import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression

BASE = Path(__file__).resolve().parents[1]
load_dotenv(BASE / ".env")
ROOT = Path(os.environ.get("RESEARCH_RESULTS_DIR", str(BASE.parents[1] / "Du_lieu/Ket_qua/Goc")))
OUT = BASE / ".runtime/evidence/forecast_audit_20261025"
METHODS = ["naive", "ma3", "linear", "random_forest"]


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUT)
    OUT = parser.parse_args().output_dir
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    protected = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.iterdir() if p.is_file()
    }
    monthly = pd.read_csv(
        ROOT / "luong_ban_theo_thang.csv", dtype={"product_id": str, "unit_alias": str}
    )
    selection = json.loads((ROOT / "lua_chon_truoc_kiem_tra.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "tong_hop_thuc_nghiem.json").read_text(encoding="utf-8"))
    pivot = (
        monthly.pivot(index="product_id", columns="month", values="positive_qty")
        .sort_index()
        .sort_index(axis=1)
    )
    matrix = pivot.to_numpy(dtype=float)
    ids = list(pivot.index)
    months = list(pivot.columns)
    assert months == [f"{year}-{month:02d}" for year in [2022, 2023] for month in range(1, 13)][:19]
    assert (monthly.positive_qty >= 0).all() and (monthly.negative_qty_abs >= 0).all()
    assert np.allclose(
        monthly.positive_qty - monthly.negative_qty_abs, monthly.net_qty, rtol=0, atol=1e-10
    )

    def inputs(t):
        x = []
        target = []
        unit = []
        for s in range(3, t):
            lag = matrix[:, s - 3 : s][:, ::-1]
            features = np.c_[lag, lag.mean(axis=1), np.full(len(ids), s % 12 + 1)]
            valid = np.isfinite(features).all(axis=1) & np.isfinite(matrix[:, s])
            x.extend(features[valid])
            target.extend(matrix[valid, s])
            unit.extend(np.flatnonzero(valid))
        x = np.asarray(x)
        target = np.asarray(target)
        unit = np.asarray(unit, dtype=int)
        eligible = np.bincount(unit, minlength=len(ids)) >= 6
        fit = eligible[unit]
        lag = matrix[:, t - 3 : t][:, ::-1]
        candidates = np.flatnonzero(eligible & np.isfinite(lag).all(axis=1))
        xx = np.c_[
            lag[candidates], lag[candidates].mean(axis=1), np.full(len(candidates), t % 12 + 1)
        ]
        return x[fit], target[fit], xx, candidates

    records = []
    rf_grid = defaultdict(list)
    for phase, times in [("validation", [12, 13, 14]), ("test", [15, 16, 17, 18])]:
        saved = pd.read_csv(
            ROOT / ("du_doan_kiem_dinh.csv" if phase == "validation" else "du_doan_kiem_tra.csv"),
            dtype={"product_id": str},
        )
        for t in times:
            X, y, xx, candidates = inputs(t)
            month = months[t]
            frame = (
                saved[saved.month == month]
                .set_index("product_id")
                .loc[[ids[i] for i in candidates]]
            )
            assert len(frame) == len(candidates) and not frame.index.duplicated().any()
            actual = matrix[candidates, t]
            assert np.allclose(frame.actual, actual, equal_nan=True)
            expected = {"naive": xx[:, 0], "ma3": xx[:, 3]}
            linear = LinearRegression().fit(X, y).predict(xx)
            assert np.allclose(frame.linear_raw, linear, rtol=1e-10, atol=1e-8)
            expected["linear"] = np.maximum(linear, 0)
            configs = (
                [
                    {"max_depth": d, "min_samples_leaf": leaf}
                    for d in [5, 10, None]
                    for leaf in [2, 5]
                ]
                if phase == "validation"
                else [selection["rf_config"]]
            )
            for j, config in enumerate(configs):
                predicted = (
                    RandomForestRegressor(**selection["rf_fixed"], **config).fit(X, y).predict(xx)
                )
                if phase == "validation":
                    assert np.allclose(frame[f"rf_{j}"], predicted, rtol=1e-10, atol=1e-8)
                    mask = np.isfinite(actual)
                    rf_grid[j].extend(np.abs(actual[mask] - predicted[mask]))
                if config == selection["rf_config"]:
                    expected["random_forest"] = predicted
            for method, predicted in expected.items():
                assert np.allclose(frame[method], predicted, rtol=1e-10, atol=1e-8), (
                    phase,
                    month,
                    method,
                )
            valid = np.isfinite(actual)
            records.append(
                {
                    "phase": phase,
                    "month": month,
                    "train_pairs": len(y),
                    "candidates": len(candidates),
                    "scored": int(valid.sum()),
                    "observed_total": int(np.isfinite(matrix[:, t]).sum()),
                    "predictions_reproduced": True,
                }
            )
            print(json.dumps(records[-1]), flush=True)
    grid_scores = [{"config_id": j, "mae": float(np.mean(error))} for j, error in rf_grid.items()]
    best = min(grid_scores, key=lambda r: (r["mae"], r["config_id"]))["config_id"]
    grid = [{"max_depth": d, "min_samples_leaf": leaf} for d in [5, 10, None] for leaf in [2, 5]]
    assert grid[best] == selection["rf_config"]
    winner = min(
        summary["validation_metrics"], key=lambda r: (r["mae"], METHODS.index(r["method"]))
    )["method"]
    assert winner == selection["winner"] == summary["selected_method"]
    X, y, xx, candidates = inputs(19)
    future = (
        pd.read_csv(ROOT / "du_bao_nghien_cuu_2023_08.csv", dtype={"product_id": str})
        .set_index("product_id")
        .loc[[ids[i] for i in candidates]]
    )
    assert winner == "naive"  # The saved study selected this baseline before the test set.
    assert np.allclose(future.forecast, xx[:, 0], rtol=0, atol=1e-10)
    assert set(future.cutoff_month) == {"2023-07"} and set(future.target_month) == {"2023-08"}
    test_records = [r for r in records if r["phase"] == "test"]
    scored = sum(r["scored"] for r in test_records)
    observed = sum(r["observed_total"] for r in test_records)
    assert protected == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.iterdir() if p.is_file()
    }
    result = {
        "at": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "seconds": round(time.monotonic() - started, 3),
        "original_results_unchanged": True,
        "folds": records,
        "rf_grid_reproduced": grid_scores,
        "selected_before_test": winner,
        "future_forecasts_reproduced": len(future),
        "test_scored_pairs": scored,
        "test_observed_pairs": observed,
        "test_observed_coverage_pct": 100 * scored / observed,
        "future_coverage_of_source_ids_pct": 100 * len(future) / len(ids),
        "research_files_sha256": protected,
    }
    (OUT / "reproduction.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ["folds", "rf_grid_reproduced", "research_files_sha256"]
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
