"""Tạo mẫu học từ lịch sử và huấn luyện mô hình dự báo theo tháng."""

from datetime import date

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

METHODS = ("naive", "ma3", "linear", "random_forest")
FEATURES = ["lag1", "lag2", "lag3", "ma3", "month_number"]


def month_add(month, offset):
    year, index = divmod(month.year * 12 + month.month - 1 + offset, 12)
    return date(year, index + 1, 1)


def transform_features(x, kind):
    if kind == "raw":
        return x
    angle = 2 * np.pi * x[:, 4] / 12
    if kind == "log":
        return np.column_stack([np.log1p(x[:, :4]), np.sin(angle), np.cos(angle)])
    scale = np.maximum(1, x[:, 3])
    lags = x[:, :3]
    return np.column_stack([
        lags / scale[:, None],
        (x[:, 0] - x[:, 1]) / scale,
        (x[:, 1] - x[:, 2]) / scale,
        lags.std(axis=1) / scale,
        (lags == 0).mean(axis=1),
        np.log1p(scale), np.sin(angle), np.cos(angle),
    ])


def fit_recipe(recipe, X, Y, future, seed=42):
    method = recipe.get("method")
    if method == "naive":
        return future[:, 0]
    if method == "ma3":
        return future[:, 3]
    if method not in ["linear", "random_forest"]:
        raise ValueError("Phương pháp không được hỗ trợ.")
    kind = recipe.get("features")
    target = recipe.get("target")
    if kind not in ["raw", "log", "scaled"] or target not in ["raw", "log", "scaled", "scaled_log"]:
        raise ValueError("Cấu hình biến đổi đặc trưng không được hỗ trợ.")

    scale = np.maximum(1, X[:, 3])
    predict_scale = np.maximum(1, future[:, 3])
    y = Y.copy()
    if target.startswith("scaled"):
        y = y / scale
    if "log" in target:
        y = np.log1p(y)
    if method == "linear":
        estimator = LinearRegression()
    else:
        depth = recipe.get("depth")
        if depth not in [5, 10]:
            raise ValueError("Độ sâu Random Forest không được hỗ trợ.")
        estimator = RandomForestRegressor(
            n_estimators=200, max_depth=depth, min_samples_leaf=2,
            random_state=seed, n_jobs=2, bootstrap=True, max_features=1.0,
        )
    pipeline = Pipeline([
        ("features", FunctionTransformer(transform_features, kw_args={"kind": kind}, validate=False)),
        ("model", estimator),
    ])
    raw = pipeline.fit(X, y).predict(future)
    if "log" in target:
        raw = np.expm1(raw)
    if target.startswith("scaled"):
        raw = raw * predict_scale
    if not np.isfinite(raw).all() or (np.abs(raw) >= 1e14).any():
        raise ValueError("Kết quả biến đổi ngoài giới hạn lưu trữ.")
    return raw


def make_samples(matrix, months):
    """Mỗi dòng học gồm ba tháng trễ và lượng bán ở tháng tiếp theo."""
    a = np.asarray(matrix, dtype=float)
    if a.ndim != 2 or not a.shape[0] or a.shape[1] < 9:
        raise ValueError("Chưa đủ lịch sử để tạo sáu cặp học có ba tháng trễ.")
    if len(months) != a.shape[1] or any(type(m) is not date or m.day != 1 for m in months):
        raise ValueError("Lịch tháng không khớp dữ liệu.")
    if any(m != month_add(months[0], i) for i, m in enumerate(months)):
        raise ValueError("Lịch tháng phải liên tục; tháng chưa biết giữ trống.")
    finite = a[np.isfinite(a)]
    if np.isinf(a).any() or (finite < 0).any() or (finite >= 1e14).any():
        raise ValueError("Lượng bán nguồn phải hữu hạn, không âm và trong giới hạn.")
    n, length = a.shape
    x_parts, y_parts, id_parts = [], [], []
    for t in range(3, length):
        lags = a[:, [t - 1, t - 2, t - 3]]
        x = np.column_stack([lags, lags.mean(axis=1), np.full(n, months[t].month)])
        mask = np.isfinite(x).all(axis=1) & np.isfinite(a[:, t])
        x_parts.append(x[mask])
        y_parts.append(a[mask, t])
        id_parts.append(np.where(mask)[0])
    X, Y, ids = np.concatenate(x_parts), np.concatenate(y_parts), np.concatenate(id_parts)
    eligible = np.bincount(ids, minlength=n) >= 6
    train = eligible[ids]
    lags = a[:, [-1, -2, -3]]
    future = np.column_stack([lags, lags.mean(axis=1), np.full(n, month_add(months[-1], 1).month)])
    indices = np.where(eligible & np.isfinite(future).all(axis=1))[0]
    if not len(indices) or not train.any():
        raise ValueError("Không có mã đủ sáu cặp học và ba tháng gần nhất liên tiếp.")
    return X[train], Y[train], future[indices], indices


def predict_origin(matrix, months, rf_config, random_seed=42, recipes=None):
    X, Y, x, indices = make_samples(matrix, months)
    if recipes is not None:
        if set(recipes) != set(METHODS):
            raise ValueError("Thiếu cấu hình của bốn phương pháp.")
        if any(recipes[method].get("method") != method for method in METHODS):
            raise ValueError("Cấu hình biến đổi không khớp tên phương pháp.")
        raw = {
            method: fit_recipe(recipes[method], X, Y, x, random_seed)
            for method in METHODS
        }
        return indices, raw, len(Y)
    linear = LinearRegression().fit(X, Y).predict(x)
    forest = (
        RandomForestRegressor(
            n_estimators=rf_config["n_estimators"],
            max_depth=rf_config["max_depth"],
            min_samples_leaf=rf_config["min_samples_leaf"],
            random_state=random_seed,
            n_jobs=2,
            bootstrap=True,
            max_features=1.0,
        )
        .fit(X, Y)
        .predict(x)
    )
    raw = {"naive": x[:, 0], "ma3": x[:, 3], "linear": linear, "random_forest": forest}
    if any(not np.isfinite(v).all() or (np.abs(v) >= 1e14).any() for v in raw.values()):
        raise ValueError("Mô hình sinh giá trị ngoài giới hạn; chưa lưu kết quả.")
    return indices, raw, len(Y)
