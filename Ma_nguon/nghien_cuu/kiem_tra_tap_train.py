import csv
import hashlib
import json
import math
from pathlib import Path

R = Path(__file__).resolve().parent
O = R.parents[1] / "Du_lieu/Huan_luyen"


def read(name):
    with (O / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


base = read("training_observed_2022.csv")
enriched = read("training_observed_2022_enriched.csv")
extra = read("source_monthly_features.csv")
assert len(base) == len(enriched) == 22461
assert len(extra) == 188537
lookup = {(r["product_id"], r["month"]): r for r in extra}
keys = set()
for row, added in zip(base, enriched):
    assert all(added[k] == value for k, value in row.items())
    assert row["target_month"] < "2023-01"
    assert row["lag3_month"] < row["lag2_month"] < row["lag1_month"] < row["target_month"]
    key = (row["product_id"], row["target_month"])
    assert key not in keys
    keys.add(key)
    assert math.isclose(float(row["ma3"]), sum(float(row[k]) for k in ["lag1", "lag2", "lag3"]) / 3)
    assert math.isclose(float(row["actual_log1p"]), math.log1p(float(row["actual"])))
    past = lookup[(row["product_id"], row["lag1_month"])]
    for k in [
        "positive_row_net_price_mean",
        "positive_row_cost_price_mean",
        "positive_selling_sites",
        "positive_selling_channels",
        "negative_rows",
    ]:
        assert added["lag1_" + k] == past[k]
quality = read("sku_data_quality.csv")
assert len(quality) == 30366
summary = json.loads((O / "training_data_audit.json").read_text(encoding="utf-8"))
assert summary["new_verified_sales_added"] == 0 and summary["raw_to_filtered_equal"]
assert sum(summary["gap_types"].values()) == summary["unknown_cells"]
assert all(
    row["normalized_match_count"] == 0
    for row in json.loads((O / "unmatched_source_rows.json").read_text(encoding="utf-8"))
)
result = {
    "passed": True,
    "initial_training_pairs": len(base),
    "enriched_training_pairs": len(enriched),
    "training_skus": len({r["product_id"] for r in base}),
    "monthly_features": len(extra),
    "quality_profiles": len(quality),
    "initial_training_contains_2023_targets": False,
    "lagged_features_strictly_before_target": True,
    "enriched_features_activated_in_model": False,
    "retained_master_missing": {
        k: sum(r[k] == "" for r in quality)
        for k in ["color", "size", "gender", "brand_name"]
        if k in quality[0]
    },
    "supplementary_feature_missing": {
        k: sum(r[k] == "" for r in enriched)
        for k in enriched[0]
        if k.startswith("lag1_positive_row")
    },
    "files": {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(O.iterdir())
        if p.is_file()
    },
}
(R / "training_exports_verification.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))
