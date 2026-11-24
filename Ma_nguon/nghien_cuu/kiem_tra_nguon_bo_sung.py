import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

R = Path(__file__).resolve().parent

import openpyxl

root = R.parents[1] / "Du_lieu/Nguon/MasterData"
results = []
for name in [
    "Master_Calendar.xlsx",
    "Distribution Channel.xlsx",
    "New_Core_Classification.xlsx",
    "COGS.xlsx",
    "Retail_price.xlsx",
]:
    p = root / name
    w = openpyxl.load_workbook(p, read_only=True, data_only=True)
    it = iter(w.active.values)
    headers = next(it)
    counts = Counter()
    years = Counter()
    ids = set()
    periods = set()
    for row in it:
        if not any(v is not None for v in row):
            continue
        item = dict(zip(headers, row))
        counts["rows"] += 1
        if "Year" in item:
            years[str(item["Year"])] += 1
        if "valid_from" in item:
            try:
                start = datetime.strptime(str(item["valid_from"]), "%d.%m.%Y").date()
                end = datetime.strptime(str(item["valid_to"]), "%d.%m.%Y").date()
                if start > end:
                    counts["reversed_interval"] += 1
                if start.year >= 2024:
                    counts["starts_2024_or_later"] += 1
                if start <= date(2023, 7, 31) and end >= date(2022, 1, 1):
                    counts["overlaps_research_period"] += 1
                periods.add((str(item["product_id"]), start, end, item["amount"]))
            except (TypeError, ValueError):
                counts["invalid_date"] += 1
            ids.add(str(item["product_id"]))
    w.close()
    result = {
        "file": name,
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        **counts,
        "calendar_years": dict(years),
        "distinct_price_records": len(periods),
        "distinct_price_skus": len(ids),
        "activated_as_model_features": False,
    }
    results.append(result)
    print(json.dumps(result), flush=True)
(R / "training_audit/additional_sources_audit.json").write_text(
    json.dumps(results, indent=2), encoding="utf-8"
)
