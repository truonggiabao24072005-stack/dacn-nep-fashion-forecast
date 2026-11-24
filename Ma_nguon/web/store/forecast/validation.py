"""Check the complete research result bundle before publishing a dataset version."""

import csv
import json
import math
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO

from store.services.documents import BusinessError

METHODS = ("naive", "ma3", "linear", "random_forest")
ARTIFACTS = (
    "source_manifest.json",
    "luong_ban_theo_thang.csv",
    "khao_sat_du_lieu.json",
    "tong_hop_thuc_nghiem.json",
    "lua_chon_truoc_kiem_tra.json",
    "du_doan_kiem_dinh.csv",
    "du_doan_kiem_tra.csv",
    "du_bao_nghien_cuu_2023_08.csv",
)


def require(condition, message):
    if not condition:
        raise BusinessError(message)


def read_bundle(root):
    try:
        blobs = {name: (root / name).read_bytes() for name in ARTIFACTS}
        optional = root / "kiem_dinh_cau_hinh_rung.csv"
        if optional.is_file():
            blobs[optional.name] = optional.read_bytes()

        def obj(name):
            return json.loads(blobs[name].decode("utf-8-sig"))

        def rows(name):
            return list(csv.DictReader(StringIO(blobs[name].decode("utf-8-sig"))))

        survey = obj("khao_sat_du_lieu.json")
        summary = obj("tong_hop_thuc_nghiem.json")
        selection = obj("lua_chon_truoc_kiem_tra.json")
        sources = obj("source_manifest.json")
        require(
            sha256(blobs["lua_chon_truoc_kiem_tra.json"]).hexdigest()
            == summary["selection_file_sha256"],
            "Tệp lựa chọn mô hình không khớp dấu kiểm tra đã chốt.",
        )
        validation = {item["method"]: item for item in summary["validation_metrics"]}
        test = {item["method"]: item for item in summary["test_metrics"]}
        require(
            len(summary["validation_metrics"]) == len(summary["test_metrics"]) == 4
            and set(validation) == set(test) == set(METHODS),
            "Phải có đủ bốn phương pháp, không trùng phương pháp.",
        )
        phase_months = {}
        pair_counts = {}
        evaluation_targets = []
        for phase, filename, stats in [
            ("validation", "du_doan_kiem_dinh.csv", validation),
            ("test", "du_doan_kiem_tra.csv", test),
        ]:
            predictions = rows(filename)
            seen = set()
            truth = []
            preds = {method: [] for method in METHODS}
            months = set()
            for row in predictions:
                key = (row["product_id"], row["month"])
                require(key not in seen, "Trùng mã hàng và tháng trong tập đánh giá.")
                seen.add(key)
                months.add(parse_month(row["month"]))
                values = {method: float(row[method]) for method in METHODS}
                require(
                    all(math.isfinite(v) and v >= 0 for v in values.values()),
                    "Dự đoán đánh giá phải hữu hạn và không âm.",
                )
                raw = row["actual"].strip()
                if raw.lower() in ("", "nan"):
                    evaluation_targets.append((row["product_id"], parse_month(row["month"]), None))
                    continue
                actual = float(raw)
                require(
                    math.isfinite(actual) and actual >= 0,
                    "Giá trị thực tế để đánh giá không hợp lệ.",
                )
                truth.append(actual)
                evaluation_targets.append((row["product_id"], parse_month(row["month"]), actual))
                for method in METHODS:
                    preds[method].append(values[method])
            require(bool(truth), "Không có cặp quan sát hợp lệ trong tập kiểm định hoặc kiểm tra.")
            for method in METHODS:
                errors = [abs(a - p) for a, p in zip(truth, preds[method])]
                positive = [error / a * 100 for a, error in zip(truth, errors) if a > 0]
                expected = {
                    "n": len(truth),
                    "n_positive_actual": len(positive),
                    "n_zero_actual": len(truth) - len(positive),
                    "mae": math.fsum(errors) / len(errors),
                    "rmse": math.sqrt(math.fsum(e * e for e in errors) / len(errors)),
                    "mape_positive_pct": math.fsum(positive) / len(positive) if positive else None,
                }
                for key, value in expected.items():
                    saved = stats[method][key]
                    valid = (
                        (saved is None)
                        if value is None
                        else (
                            isinstance(saved, (int, float))
                            and not isinstance(saved, bool)
                            and math.isfinite(saved)
                            and math.isclose(saved, value, rel_tol=1e-10, abs_tol=1e-10)
                        )
                    )
                    require(valid, "Chỉ số sai số hoặc số cặp đánh giá không khớp CSV dự đoán.")
            phase_months[phase] = months
            pair_counts[phase] = len(truth)
        require(
            max(phase_months["validation"]) < min(phase_months["test"]),
            "Tháng kiểm định phải đứng trước tháng kiểm tra.",
        )
        winner = min(METHODS, key=lambda method: (validation[method]["mae"], METHODS.index(method)))
        require(
            selection["winner"] == summary["selected_method"] == winner,
            "Phương pháp được chọn không khớp MAE kiểm định.",
        )
        require(
            selection["validation_metrics"] == summary["validation_metrics"],
            "Chỉ số kiểm định khác tệp đã chốt lựa chọn.",
        )
        monthly = rows("luong_ban_theo_thang.csv")
        aliases = {}
        months = set()
        seen = set()
        source_rows = 0
        monthly_targets = {}
        for row in monthly:
            pid = row["product_id"]
            month = parse_month(row["month"])
            months.add(month)
            require((pid, month) not in seen, "Trùng khóa mã hàng và tháng trong dữ liệu đã lọc.")
            seen.add((pid, month))
            require(
                pid not in aliases or aliases[pid] == row["unit_alias"],
                "Mã nghiên cứu ánh xạ không nhất quán.",
            )
            aliases[pid] = row["unit_alias"]
            pos, neg, net = [
                Decimal(row[key]) for key in ["positive_qty", "negative_qty_abs", "net_qty"]
            ]
            require(
                all(v.is_finite() and abs(v) < Decimal("1e14") for v in [pos, neg, net])
                and pos >= 0
                and neg >= 0
                and pos - neg == net,
                "Số lượng tháng không hợp lệ hoặc vượt giới hạn lưu trữ.",
            )
            count = int(row["source_rows"])
            require(count > 0, "Số dòng nguồn của tháng quan sát phải dương.")
            source_rows += count
            monthly_targets[(pid, month)] = float(pos)
        require(
            months
            and len(monthly) == survey["observed_unit_months"]
            and len(aliases) == survey["unique_retained_product_ids"]
            and source_rows == survey["counts"]["retained_rows"],
            "Số dòng hoặc số mã đã lọc không khớp báo cáo chất lượng.",
        )
        require(
            phase_months["validation"] | phase_months["test"] <= months,
            "Kỳ đánh giá nằm ngoài phạm vi dữ liệu tháng.",
        )
        for pid, month, actual in evaluation_targets:
            require(pid in aliases, "Mã đánh giá không tồn tại trong dữ liệu đã lọc.")
            observed = monthly_targets.get((pid, month))
            require(
                (actual is None and observed is None)
                or (
                    actual is not None
                    and observed is not None
                    and math.isclose(actual, observed, rel_tol=1e-10, abs_tol=1e-10)
                ),
                "Giá trị thực tế trong tập đánh giá không khớp dữ liệu tháng.",
            )
        cutoff = max(months)
        target = date(cutoff.year + (cutoff.month == 12), cutoff.month % 12 + 1, 1)
        future = rows("du_bao_nghien_cuu_2023_08.csv")
        future_ids = set()
        for row in future:
            pid = row["product_id"]
            forecast = Decimal(row["forecast"])
            require(
                pid in aliases and pid not in future_ids,
                "Mã dự báo bị trùng hoặc không có trong bộ dữ liệu.",
            )
            require(
                row["unit_alias"] == aliases[pid], "Bí danh trong dự báo không khớp mã dữ liệu."
            )
            require(
                parse_month(row["cutoff_month"]) == cutoff
                and parse_month(row["target_month"]) == target
                and row["method"] == winner,
                "Mốc chốt, tháng dự báo hoặc phương pháp không khớp bộ kết quả đã chốt.",
            )
            require(
                forecast.is_finite() and 0 <= forecast < Decimal("1e14"),
                "Kết quả dự báo phải hữu hạn, không âm và trong giới hạn lưu trữ.",
            )
            future_ids.add(pid)
        require(
            len(future) > 0 and len(future) == summary["future_research_forecast_count"],
            "Số dự báo không khớp báo cáo thực nghiệm.",
        )
        require(
            len(sources) > 0
            and len({r["file"] for r in sources}) == len(sources)
            and len({r["sha256"] for r in sources}) == len(sources),
            "Danh sách tệp nguồn trùng hoặc trống.",
        )
        digest = sha256()
        for name, data in sorted(blobs.items()):
            digest.update(name.encode())
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
        return {
            "digest": digest.hexdigest(),
            "blobs": blobs,
            "monthly": monthly,
            "future": future,
            "survey": survey,
            "summary": summary,
            "selection": selection,
            "sources": sources,
            "validation": validation,
            "test": test,
            "coverage_start": min(months),
            "cutoff": cutoff,
            "target": target,
            "pair_counts": pair_counts,
            "artifact_hashes": {name: sha256(data).hexdigest() for name, data in blobs.items()},
        }
    except BusinessError:
        raise
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        InvalidOperation,
        OverflowError,
    ) as exc:
        raise BusinessError(
            "Bộ kết quả nghiên cứu thiếu tệp, sai cấu trúc hoặc chứa giá trị không hợp lệ. Kiểm tra lại các CSV và JSON."
        ) from exc


def parse_month(value):
    parsed = date.fromisoformat(value + "-01")
    require(len(value) == 7 and parsed.isoformat()[:7] == value, "Tháng phải có dạng YYYY-MM.")
    return parsed
