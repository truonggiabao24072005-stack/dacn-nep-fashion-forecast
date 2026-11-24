"""Đọc lượng bán theo tháng, giữ nguyên những tháng chưa có quan sát."""

import csv
import math
from datetime import date
from pathlib import Path

import numpy as np


def month_add(month, offset):
    year, index = divmod(month.year * 12 + month.month - 1 + offset, 12)
    return date(year, index + 1, 1)


def read_monthly(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"product_id", "unit_alias", "month", "positive_qty"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Tệp tháng thiếu mã nguồn, mã hàng, tháng hoặc lượng bán.")
        rows = list(reader)
    if not rows:
        raise ValueError("Tệp lượng bán theo tháng đang trống.")
    observed = set()
    for line, row in enumerate(rows, 2):
        key = row["product_id"].strip()
        month = date.fromisoformat(row["month"] + "-01")
        quantity = float(row["positive_qty"])
        if not key or not math.isfinite(quantity) or not 0 <= quantity < 1e14:
            raise ValueError(f"Dòng {line}: mã nguồn hoặc lượng bán không hợp lệ.")
        if (key, month) in observed:
            raise ValueError(f"Dòng {line}: trùng mã nguồn và tháng.")
        if "negative_qty_abs" in row and "net_qty" in row:
            negative = float(row["negative_qty_abs"])
            net = float(row["net_qty"])
            if not math.isfinite(negative) or negative < 0 or not math.isfinite(net):
                raise ValueError(f"Dòng {line}: lượng âm hoặc lượng ròng không hợp lệ.")
            if not math.isclose(quantity - negative, net, abs_tol=1e-8, rel_tol=1e-12):
                raise ValueError(f"Dòng {line}: lượng dương, âm và ròng không khớp.")
        row["product_id"] = key
        row["date"] = month
        row["quantity"] = quantity
        observed.add((key, month))
    return rows


def monthly_matrix(rows):
    products = sorted({row["product_id"] for row in rows})
    start = min(row["date"] for row in rows)
    end = max(row["date"] for row in rows)
    count = (end.year - start.year) * 12 + end.month - start.month + 1
    months = [month_add(start, i) for i in range(count)]
    positions = {key: i for i, key in enumerate(products)}
    calendar = {month: i for i, month in enumerate(months)}
    matrix = np.full((len(products), len(months)), np.nan)
    aliases = {}
    for row in rows:
        key = row["product_id"]
        if key in aliases and aliases[key] != row["unit_alias"]:
            raise ValueError("Một mã nguồn đang có nhiều mã hàng đối chiếu.")
        aliases[key] = row["unit_alias"]
        matrix[positions[key], calendar[row["date"]]] = row["quantity"]
    return products, months, matrix, aliases
