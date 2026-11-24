"""Reconcile raw workbooks; supplement traceable training inputs, never invent sales."""

import csv
import hashlib
import json
import math
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

R = Path(__file__).resolve().parent
B = R.parent

import openpyxl

ROOT = R.parents[1] / "Du_lieu/Nguon"
OUT = R.parents[1] / "Du_lieu/Huan_luyen"
OUT.mkdir(parents=True, exist_ok=True)


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )


def emit(value):
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)


def write_csv(name, columns, rows):
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def source(path):
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    iterator = iter(workbook.active.values)
    headers = next(iterator)
    return workbook, list(headers), iterator


w, head, it = source(ROOT / "MasterData/Productmaster.xlsx")
master = {}
duplicates = []
missing_master = Counter()
blank = 0
for row in it:
    if not any(v is not None for v in row):
        blank += 1
        continue
    item = dict(zip(head, row))
    pid = item["product_id"]
    if pid in master:
        duplicates.append(str(pid))
    master[pid] = item
    missing_master.update(k for k, v in item.items() if v is None or v == "")
w.close()
emit({"master_rows": len(master), "headers": head, "duplicate_ids": len(duplicates)})

aggregates = defaultdict(lambda: [0.0, 0.0, 0])
files = []
unmatched = []
invalid = []
signed = Counter()
enrichment = defaultdict(
    lambda: {
        "net_sum": 0.0,
        "net_n": 0,
        "cost_sum": 0.0,
        "cost_n": 0,
        "sites": set(),
        "channels": set(),
        "positive_rows": 0,
        "negative_rows": 0,
    }
)
all_header = None
for path in sorted((ROOT / "Sales_snapshot_data").glob("*.xlsx")):
    w, head, it = source(path)
    all_header = head if all_header is None else all_header
    assert head == all_header, "Sales schema differs"
    stats = Counter()
    seen = set()
    business_keys = Counter()
    months = Counter()
    for lineno, row in enumerate(it, 2):
        if not any(v is not None for v in row):
            stats["blank_rows"] += 1
            continue
        stats["source_rows"] += 1
        item = dict(zip(head, row))
        signature = tuple(row)
        if signature in seen:
            stats["exact_duplicate_rows"] += 1
        seen.add(signature)
        pid, rawmo, q = item["product_id"], item["month"], item["sold_quantity"]
        business_keys[(pid, rawmo, item.get("site"), item.get("channel_id"))] += 1
        try:
            code = int(rawmo)
            year, month = divmod(code, 1000)
            if (
                isinstance(rawmo, bool)
                or float(rawmo) != code
                or year not in [2022, 2023]
                or not 1 <= month <= 12
            ):
                raise ValueError()
            idx = (year - 2022) * 12 + month - 1
            if idx > 18:
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            stats["invalid_month"] += 1
            invalid.append({"file": path.name, "row": lineno, "reason": "invalid_month", **item})
            continue
        if isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q):
            stats["invalid_quantity"] += 1
            invalid.append({"file": path.name, "row": lineno, "reason": "invalid_quantity", **item})
            continue
        label = f"{year}-{month:02d}"
        months[label] += 1
        stats["negative_rows" if q < 0 else "zero_rows" if q == 0 else "positive_rows"] += 1
        if pid not in master:
            stats["unmatched_master"] += 1
            # Only a unique exact trimmed ID match is eligible for a proposed repair.
            candidates = [key for key in master if str(key).strip() == str(pid).strip()]
            unmatched.append(
                {
                    "file": path.name,
                    "row": lineno,
                    "normalized_match_count": len(candidates),
                    "normalized_match": str(candidates[0]) if len(candidates) == 1 else "",
                    **item,
                }
            )
            continue
        group = aggregates[(str(pid), label)]
        group[0] += max(float(q), 0)
        group[1] += max(-float(q), 0)
        group[2] += 1
        extra = enrichment[(str(pid), label)]
        if q > 0:
            extra["positive_rows"] += 1
            extra["sites"].add(str(item["site"]))
            extra["channels"].add(str(item["channel_id"]))
            for field, prefix in [("net_price", "net"), ("cost_price", "cost")]:
                price = item.get(field)
                if (
                    isinstance(price, (int, float))
                    and not isinstance(price, bool)
                    and math.isfinite(price)
                ):
                    extra[prefix + "_sum"] += price
                    extra[prefix + "_n"] += 1
        elif q < 0:
            extra["negative_rows"] += 1
        stats["retained_rows"] += 1
    w.close()
    files.append(
        {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **stats,
            "months": dict(months),
            "repeated_product_site_channel_month_keys": sum(n > 1 for n in business_keys.values()),
        }
    )
    signed.update(stats)
    emit(files[-1])

with (R.parents[1] / "Du_lieu/Ket_qua/Goc/luong_ban_theo_thang.csv").open(
    encoding="utf-8-sig", newline=""
) as f:
    filtered = list(csv.DictReader(f))
reference = {
    (r["product_id"], r["month"]): (
        float(r["positive_qty"]),
        float(r["negative_qty_abs"]),
        int(r["source_rows"]),
    )
    for r in filtered
}
assert set(reference) == set(aggregates)
mismatches = []
for key, actual in aggregates.items():
    expected = reference[key]
    if any(not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8) for a, b in zip(actual, expected)):
        mismatches.append({"key": key, "raw": actual, "filtered": expected})
assert not mismatches, mismatches[:5]
calendar = [f"{2022+i//12}-{i%12+1:02}" for i in range(19)]
matrix = defaultdict(dict)
aliases = {}
for row in filtered:
    matrix[row["product_id"]][row["month"]] = float(row["positive_qty"])
    aliases[row["product_id"]] = row["unit_alias"]
profiles = []
training = []
origins = []
gap_totals = Counter()
attributes = [
    k
    for k in [
        "product_group",
        "color",
        "size",
        "gender",
        "brand_name",
        "shoe_product",
        "product_syle",
    ]
    if k in next(iter(master.values()))
]
for pid, months in sorted(matrix.items()):
    observed = sorted(months)
    first, last = calendar.index(observed[0]), calendar.index(observed[-1])
    gaps = [m for m in calendar[first : last + 1] if m not in months]
    gap_totals["leading_unknown"] += first
    gap_totals["internal_unknown"] += len(gaps)
    gap_totals["trailing_unknown"] += 18 - last
    profile = {
        "unit_alias": aliases[pid],
        "product_id": pid,
        "observed_months": len(months),
        "first_observed_month": observed[0],
        "last_observed_month": observed[-1],
        "leading_unknown": first,
        "internal_unknown": len(gaps),
        "trailing_unknown": 18 - last,
        "internal_unknown_months": "|".join(gaps),
        **{k: master[pid].get(k) for k in attributes},
    }
    profiles.append(profile)
    pairs = []
    for t in range(3, 12):
        needed = [calendar[t - i] for i in [0, 1, 2, 3]]
        if all(m in months for m in needed):
            lag = [months[calendar[t - i]] for i in [1, 2, 3]]
            angle = 2 * math.pi * (t % 12 + 1) / 12
            pairs.append(
                {
                    "unit_alias": aliases[pid],
                    "product_id": pid,
                    "target_month": calendar[t],
                    "lag1_month": calendar[t - 1],
                    "lag2_month": calendar[t - 2],
                    "lag3_month": calendar[t - 3],
                    "lag1": lag[0],
                    "lag2": lag[1],
                    "lag3": lag[2],
                    "ma3": sum(lag) / 3,
                    "month_number": t % 12 + 1,
                    "month_sin": math.sin(angle),
                    "month_cos": math.cos(angle),
                    "actual": months[calendar[t]],
                    "actual_log1p": math.log1p(months[calendar[t]]),
                }
            )
    if len(pairs) >= 6:
        training.extend(pairs)
for t in range(12, 20):
    eligible = candidates = observed_targets = 0
    training_pairs = 0
    for pid, months in matrix.items():
        pairs = sum(all(calendar[s - i] in months for i in range(4)) for s in range(3, min(t, 19)))
        if pairs >= 6:
            eligible += 1
            training_pairs += pairs
            if all(calendar[t - i] in months for i in [1, 2, 3]):
                candidates += 1
        if t < 19 and calendar[t] in months:
            observed_targets += 1
    origins.append(
        {
            "target_month": f"2023-{t-11:02}",
            "phase": "Validation" if t < 15 else "Test" if t < 19 else "Future",
            "eligible_skus": eligible,
            "forecast_candidates": candidates,
            "training_pairs": training_pairs,
            "observed_target_skus": observed_targets,
        }
    )

write_csv("sku_data_quality.csv", list(profiles[0]), profiles)
write_csv("training_observed_2022.csv", list(training[0]), training)
monthly_extra = []
for (pid, month), extra in sorted(enrichment.items()):
    monthly_extra.append(
        {
            "unit_alias": aliases[pid],
            "product_id": pid,
            "month": month,
            "positive_row_net_price_mean": (
                extra["net_sum"] / extra["net_n"] if extra["net_n"] else None
            ),
            "positive_row_cost_price_mean": (
                extra["cost_sum"] / extra["cost_n"] if extra["cost_n"] else None
            ),
            "net_price_observed_positive_rows": extra["net_n"],
            "cost_price_observed_positive_rows": extra["cost_n"],
            "positive_rows": extra["positive_rows"],
            "negative_rows": extra["negative_rows"],
            "positive_selling_sites": len(extra["sites"]),
            "positive_selling_channels": len(extra["channels"]),
        }
    )
write_csv("source_monthly_features.csv", list(monthly_extra[0]), monthly_extra)
extra_lookup = {(r["product_id"], r["month"]): r for r in monthly_extra}
enriched = []
for row in training:
    past = extra_lookup[(row["product_id"], row["lag1_month"])]
    enriched.append(
        {
            **row,
            **{
                "lag1_" + key: past[key]
                for key in [
                    "positive_row_net_price_mean",
                    "positive_row_cost_price_mean",
                    "positive_selling_sites",
                    "positive_selling_channels",
                    "negative_rows",
                ]
            },
            **{key: master[row["product_id"]].get(key) for key in attributes},
        }
    )
write_csv("training_observed_2022_enriched.csv", list(enriched[0]), enriched)
save(
    "feature_contract.json",
    {
        "target": "actual = recorded positive sold quantity; original quantities preserved",
        "initial_training_cutoff": "2022-12",
        "training_target_months": "2022-04 through 2022-12",
        "lag_months": "strictly earlier than target_month; calendar months, no gap bridging",
        "added_source_features": "previous-month raw positive-row net_price/cost_price means, distinct selling sites/channels, negative row counts",
        "price_semantics": "mean of source field values per positive row; not asserted to be revenue, current price or verified unit price",
        "static_attributes": "source master values; historical availability not proven, therefore not used by the installed model",
        "model_adoption": "enriched fields prepared for separate Validation ablation; installed v2 still uses documented lag/calendar/log features only",
        "sku_data_quality_usage": "audit only; full-period observation counts must not be fed to an earlier forecast origin",
        "missing_policy": "blank = unknown; no synthetic sales, zero imputation or external SKU mixing",
        "holdout_policy": "no Validation/Test target rows appended to initial 2022 Training set",
    },
)
write_csv("rolling_origin_counts.csv", list(origins[0]), origins)
save("unmatched_source_rows.json", unmatched)
save("invalid_source_rows.json", invalid)
archives = {}
for path in [ROOT.parents[1] / "archive.zip"]:
    if path.exists():
        with zipfile.ZipFile(path) as z:
            archives[str(path)] = {
                "sales_workbooks": [
                    n for n in z.namelist() if "Sales_snapshot_data" in n and n.endswith(".xlsx")
                ]
            }
inventory = []
for path in sorted((ROOT / "Inventory_snapshot_data").glob("*.xlsx")):
    w, h, it = source(path)
    inventory.append(
        {"file": path.name, "headers": h, "first_rows": [row for _, row in zip(range(2), it)]}
    )
    w.close()
summary = {
    "raw_master_rows": len(master),
    "master_duplicate_ids": duplicates,
    "master_missing_values": dict(missing_master),
    "raw_sales_schema": all_header,
    "raw_sales_files": len(files),
    "sales_counts": dict(signed),
    "files": files,
    "raw_to_filtered_equal": True,
    "reconciled_monthly_rows": len(reference),
    "retained_skus": len(matrix),
    "calendar_months": 19,
    "grid_cells": len(matrix) * 19,
    "observed_cells": len(reference),
    "unknown_cells": len(matrix) * 19 - len(reference),
    "gap_types": dict(gap_totals),
    "observed_zero_positive_flow_cells": sum(
        q == 0 for months in matrix.values() for q in months.values()
    ),
    "initial_2022_training_pairs": len(training),
    "origins": origins,
    "archives": archives,
    "inventory_previews": inventory,
    "enriched_training_pairs": len(enriched),
    "source_monthly_feature_rows": len(monthly_extra),
    "new_verified_sales_added": 0,
    "source_rows_quarantined": len(unmatched) + len(invalid),
    "policy": "No zero filling, no row deletion without transaction identity, no invented price/promotion/stock-out labels; added traceable master metadata and supervised training export only.",
}
save("training_data_audit.json", summary)
emit(
    {
        k: v
        for k, v in summary.items()
        if k not in ["files", "inventory_previews", "archives", "origins"]
    }
)
