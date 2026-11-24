"""Huấn luyện và đối chiếu bốn phương pháp dự báo theo thứ tự thời gian."""

import argparse
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "web"))

from du_lieu import monthly_matrix, read_monthly
from store.forecast.metrics import point_metrics, training_scale
from store.forecast.training import FEATURES, METHODS, month_add, predict_origin


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def load_data(data_dir):
    monthly = data_dir / "Ket_qua/Goc/luong_ban_theo_thang.csv"
    selection_file = data_dir / "Ket_qua/Random_Forest/selection_before_test.json"
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    rows = read_monthly(monthly)
    products, months, matrix, aliases = monthly_matrix(rows)
    expected = [month_add(date(2022, 1, 1), i) for i in range(19)]
    if months != expected:
        raise ValueError("Cấu hình nghiên cứu hiện tại dùng lịch từ 01/2022 đến 07/2023.")
    if selection["criterion"] != "Validation MAE":
        raise ValueError("Tiêu chí chọn mô hình phải là Validation MAE.")
    if set(selection["recipe_winners"]) != set(METHODS):
        raise ValueError("Cấu hình không đủ bốn phương pháp của nghiên cứu.")
    return {
        "rows": rows, "products": products, "months": months, "matrix": matrix,
        "aliases": aliases, "selection": selection,
        "source_sha256": hashlib.sha256(monthly.read_bytes()).hexdigest(),
    }


def train_models(data, progress=print):
    """Mỗi kỳ chỉ dùng lịch sử trước tháng cần dự đoán."""
    products = data["products"]
    months = data["months"]
    matrix = data["matrix"]
    predictions, origins = [], []
    for t in range(12, 20):
        target = month_add(months[0], t)
        ids, raw, pairs = predict_origin(
            matrix[:, :t].copy(), months[:t], {}, 42,
            recipes=data["selection"]["recipe_winners"],
        )
        values = {method: np.maximum(raw[method], 0) for method in METHODS}
        scored = 0
        for index, i in enumerate(ids):
            key = products[int(i)]
            actual = matrix[i, t] if t < matrix.shape[1] else np.nan
            known = np.isfinite(actual)
            scored += int(known)
            predictions.append({
                "product_id": key, "unit_alias": data["aliases"][key],
                "month": target.strftime("%Y-%m"),
                "phase": "validation" if t < 15 else "test" if t < 19 else "forecast",
                "actual": float(actual) if known else "",
                **{method: float(values[method][index]) for method in METHODS},
            })
        origin = {
            "target": str(target), "cutoff": str(months[min(t, 19) - 1]),
            "training_pairs": pairs, "candidate_skus": len(ids), "scored_pairs": scored,
        }
        origins.append(origin)
        if progress:
            progress(f"{target:%m/%Y}: {pairs:,} mẫu học, {len(ids):,} mã dự đoán, {scored:,} cặp có thực tế.")
    return predictions, origins


def evaluate(data, predictions):
    histories = defaultdict(list)
    for row in data["rows"]:
        histories[row["product_id"]].append((row["date"], row["quantity"]))
    metrics = {}
    for phase in ["validation", "test"]:
        rows = [r for r in predictions if r["phase"] == phase and r["actual"] != ""]
        scales = [
            training_scale(histories[r["product_id"]], date.fromisoformat(r["month"] + "-01"))
            for r in rows
        ]
        metrics[phase] = {
            method: point_metrics([r["actual"] for r in rows], [r[method] for r in rows], scales)
            for method in METHODS
        }
    selected = min(METHODS, key=lambda m: metrics["validation"][m]["mae"])
    if selected != data["selection"]["selected_method"]:
        raise ValueError("Lựa chọn trên tập kiểm định khác cấu hình; cần đối chiếu trước khi công bố.")
    return selected, metrics


def verify_reference(data, predictions, metrics, data_dir):
    if data["source_sha256"] != data["selection"]["source_monthly_sha256"]:
        raise ValueError("Dữ liệu tháng khác phiên bản đã chốt.")
    folder = data_dir / "Ket_qua/Random_Forest"
    reference = {(r["product_id"], r["month"]): r for r in read_csv(folder / "test_predictions.csv")}
    future = {r["product_id"]: r for r in read_csv(folder / "future_predictions.csv")}
    checked = {"test_pairs": 0, "future_skus": 0}
    for row in predictions:
        if row["phase"] == "test" and row["actual"] != "":
            old = reference.pop((row["product_id"], row["month"]))
            if float(old["actual"]) != row["actual"]:
                raise ValueError("Lượng thực tế không khớp bản đối chiếu.")
            checked["test_pairs"] += 1
        elif row["phase"] == "forecast":
            old = future.pop(row["product_id"])
            checked["future_skus"] += 1
        else:
            continue
        for method in METHODS:
            if not np.isclose(row[method], float(old[method]), rtol=0, atol=1e-8):
                raise ValueError(f"Dự đoán {row['unit_alias']} khác bản đối chiếu: {method}.")
    if reference or future:
        raise ValueError("Còn cặp đã chốt chưa được dự đoán trong lần chạy này.")
    for method in METHODS:
        name = data["selection"]["recipe_winners"][method]["id"]
        saved = data["selection"]["validation_scores"][name]
        for key in ["mae", "rmse", "mape_positive_pct"]:
            if not np.isclose(metrics["validation"][method][key], saved[key], rtol=0, atol=1e-8):
                raise ValueError("Chỉ số tập kiểm định không khớp bản đã chốt.")
    return checked


def save_results(output, data, predictions, origins, selected, metrics, checked, elapsed):
    output.mkdir(parents=True, exist_ok=False)
    with (output / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    with (output / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["phase", "method", *metrics["test"]["naive"]])
        writer.writeheader()
        for phase in metrics:
            for method in METHODS:
                writer.writerow({"phase": phase, "method": method, **metrics[phase][method]})
    observed_test = sum(row["date"] >= date(2023, 4, 1) for row in data["rows"])
    scored_test = metrics["test"][selected]["n"]
    result = {
        "completed_at": datetime.now(timezone.utc).isoformat(), "selected_method": selected,
        "selection_criterion": "Validation MAE", "source_monthly_sha256": data["source_sha256"],
        "features": FEATURES, "recipes": data["selection"]["recipe_winners"], "metrics": metrics,
        "test_observed_pairs": observed_test, "test_scored_pairs": scored_test,
        "test_coverage_pct": scored_test * 100 / observed_test if observed_test else None,
        "reference_check": checked, "origins": origins, "elapsed_seconds": elapsed,
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "training_code_sha256": hashlib.sha256((HERE.parent / "web/store/forecast/training.py").read_bytes()).hexdigest(),
    }
    (output / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    return result


def plot_product(predictions, alias, selected, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [r for r in predictions if r["unit_alias"] == alias and r["phase"] != "validation"]
    if not rows:
        raise ValueError("Mã sản phẩm không có dự đoán trong lần chạy.")
    actual = [float(r["actual"]) if r["actual"] != "" else np.nan for r in rows]
    forecast = [r[selected] for r in rows]
    difference = [p - a if np.isfinite(a) else np.nan for p, a in zip(forecast, actual)]
    labels = [r["month"] for r in rows]
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(labels, actual, "o-", color="#1b6c50", label="Thực tế")
    axes[0].plot(labels, forecast, "o--", color="#bc7023", label="Dự đoán")
    axes[0].set_title(f"Nhu cầu sản phẩm {alias}")
    axes[0].set_ylabel("Đơn vị nguồn")
    axes[0].legend()
    axes[1].bar(labels, difference, color=["#aa493d" if d < 0 else "#457e67" for d in difference])
    axes[1].axhline(0, color="#777", linewidth=1)
    axes[1].set_ylabel("Dự đoán − Thực tế")
    for ax in axes:
        ax.grid(axis="y", alpha=.2)
    fig.tight_layout()
    fig.savefig(output / f"du_bao_{alias}.png", dpi=180)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Huấn luyện từ CSV, không cần kết nối cơ sở dữ liệu.")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("DACN_DATA_DIR", HERE.parents[1] / "Du_lieu")))
    parser.add_argument("--output-dir", type=Path, default=HERE / "ket_qua_chay_lai" / datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--verify-reference", action="store_true", help="Đối chiếu từng dự đoán với bản đã chốt.")
    parser.add_argument("--product", default="MH00381", help="Mã hàng xuất biểu đồ, ví dụ MH00381.")
    args = parser.parse_args(argv)
    if args.output_dir.resolve().is_relative_to(args.data_dir.resolve()):
        parser.error("Chọn thư mục kết quả mới bên ngoài dữ liệu đã công bố.")
    if args.output_dir.exists():
        parser.error("Thư mục kết quả đã có; chọn tên mới để giữ lần chạy trước.")
    tick = time.monotonic()
    print("1. Đọc và kiểm tra dữ liệu tháng.", flush=True)
    data = load_data(args.data_dir)
    if args.product not in data["aliases"].values():
        parser.error("Mã sản phẩm không có trong dữ liệu nguồn.")
    if args.verify_reference and data["source_sha256"] != data["selection"]["source_monthly_sha256"]:
        parser.error("Dữ liệu tháng khác phiên bản đã chốt.")
    print("2. Tạo mẫu học từ ba tháng trước; chia kỳ theo thời gian.", flush=True)
    print("3. Huấn luyện bốn phương pháp theo cấu hình kiểm định.", flush=True)
    predictions, origins = train_models(data)
    print("4. Đánh giá trên cùng các cặp có thực tế.", flush=True)
    selected, metrics = evaluate(data, predictions)
    if not any(r["unit_alias"] == args.product and r["phase"] != "validation" for r in predictions):
        raise ValueError("Mã sản phẩm chưa đủ lịch sử để xuất biểu đồ dự đoán.")
    checked = verify_reference(data, predictions, metrics, args.data_dir) if args.verify_reference else None
    print("5. Lưu dự đoán và chỉ số vào thư mục mới.", flush=True)
    result = save_results(args.output_dir, data, predictions, origins, selected, metrics, checked, time.monotonic() - tick)
    print("6. Vẽ dự đoán, thực tế và chênh lệch.", flush=True)
    plot_product(predictions, args.product, selected, args.output_dir)
    print(json.dumps({"selected_method": selected, "test_metrics": metrics["test"][selected], "output": str(args.output_dir)}, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise SystemExit(f"Không hoàn tất huấn luyện: {exc}") from exc
