"""Reconcile the monthly training table against the original Excel snapshots."""

import argparse
import csv
import hashlib
import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import openpyxl
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parents[1]
load_dotenv(BASE / ".env")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("DACN_SOURCE_DIR", str(BASE.parents[1] / "Du_lieu/Nguon"))),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=BASE / ".runtime/evidence/forecast_audit_20261025"
    )
    args = parser.parse_args()
    started = time.monotonic()
    results = Path(
        os.environ.get("RESEARCH_RESULTS_DIR", str(BASE.parents[1] / "Du_lieu/Ket_qua/Goc"))
    )
    manifest = json.loads((results / "source_manifest.json").read_text(encoding="utf-8"))
    survey = json.loads((results / "khao_sat_du_lieu.json").read_text(encoding="utf-8"))
    for entry in manifest:
        path = args.root / entry["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    master_path = args.root / "MasterData/Productmaster.xlsx"
    workbook = openpyxl.load_workbook(master_path, read_only=True, data_only=True)
    iterator = iter(workbook.active.values)
    header = list(next(iterator))
    key = header.index("product_id")
    master = {str(row[key]) for row in iterator if any(cell is not None for cell in row)}
    workbook.close()
    totals = Counter()
    groups = {}
    files = []
    for entry in manifest:
        if Path(entry["file"]).name == "Productmaster.xlsx":
            continue
        path = args.root / entry["file"]
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        iterator = iter(workbook.active.values)
        header = list(next(iterator))
        pid_index = header.index("product_id")
        month_index = header.index("month")
        qty_index = header.index("sold_quantity")
        counts = Counter()
        for row in iterator:
            if not any(cell is not None for cell in row):
                continue
            counts["source_rows"] += 1
            try:
                code = int(row[month_index])
                year, month = divmod(code, 1000)
                if (
                    float(row[month_index]) != code
                    or not (2022, 1) <= (year, month) <= (2023, 7)
                    or not 1 <= month <= 12
                ):
                    raise ValueError()
            except (ValueError, TypeError):
                counts["invalid_month_rows"] += 1
                continue
            raw = row[qty_index]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                counts["invalid_quantity_rows"] += 1
                continue
            amount = Decimal(str(raw))
            counts[
                "positive_rows" if amount > 0 else "negative_rows" if amount < 0 else "zero_rows"
            ] += 1
            pid = str(row[pid_index])
            if pid not in master:
                counts["unmatched_master_rows"] += 1
                continue
            counts["retained_rows"] += 1
            cell = groups.setdefault((pid, f"{year}-{month:02d}"), [Decimal(0), Decimal(0), 0])
            cell[0] += max(amount, Decimal(0))
            cell[1] += max(-amount, Decimal(0))
            cell[2] += 1
        workbook.close()
        totals.update(counts)
        files.append({"file": str(entry["file"]), **counts})
        print(
            json.dumps({"verified_file": path.name, "source_rows": counts["source_rows"]}),
            flush=True,
        )
    mismatches = []
    with (results / "luong_ban_theo_thang.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            key = (row["product_id"], row["month"])
            actual = groups.pop(key, None)
            if (
                actual is None
                or abs(actual[0] - Decimal(row["positive_qty"])) > Decimal("1e-8")
                or abs(actual[1] - Decimal(row["negative_qty_abs"])) > Decimal("1e-8")
                or actual[2] != int(row["source_rows"])
            ):
                mismatches.append({"product_id": key[0], "month": key[1]})
    for key in totals:
        assert totals[key] == survey["counts"].get(key, 0), (
            key,
            totals[key],
            survey["counts"].get(key),
        )
    assert len(master) == survey["master_rows"]
    result = {
        "at": datetime.now(timezone.utc).isoformat(),
        "passed": not groups and not mismatches,
        "source_files_verified": len(manifest),
        "original_results_modified": False,
        "monthly_mismatches": len(mismatches),
        "unexpected_monthly_groups": len(groups),
        "counts": dict(totals),
        "seconds": round(time.monotonic() - started, 3),
        "files": files,
    }
    output = args.output_dir / "source_reconciliation.json"
    output.parent.mkdir(exist_ok=True, parents=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}), flush=True)
    assert result["passed"]


if __name__ == "__main__":
    main()
