"""Versioned feature transformations, fitted only on the supplied past samples."""

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression

from store.services.documents import BusinessError


def fit_recipe(recipe, X, Y, future, seed=42):
    method = recipe.get("method")
    if method == "naive":
        return future[:, 0]
    if method == "ma3":
        return future[:, 3]
    if method not in ["linear", "random_forest"]:
        raise BusinessError("Phương pháp không được hỗ trợ.")
    kind = recipe.get("features")
    target = recipe.get("target")
    if kind not in ["raw", "log", "scaled"] or target not in ["raw", "log", "scaled", "scaled_log"]:
        raise BusinessError("Cấu hình biến đổi đặc trưng không được hỗ trợ.")

    def transform(x):
        scale = np.maximum(1, x[:, 3])
        if kind == "raw":
            return x, scale
        angle = 2 * np.pi * x[:, 4] / 12
        if kind == "log":
            return np.column_stack([np.log1p(x[:, :4]), np.sin(angle), np.cos(angle)]), scale
        lags = x[:, :3]
        return (
            np.column_stack(
                [
                    lags / scale[:, None],
                    (x[:, 0] - x[:, 1]) / scale,
                    (x[:, 1] - x[:, 2]) / scale,
                    lags.std(axis=1) / scale,
                    (lags == 0).mean(axis=1),
                    np.log1p(scale),
                    np.sin(angle),
                    np.cos(angle),
                ]
            ),
            scale,
        )

    train, scale = transform(X)
    predict, predict_scale = transform(future)
    y = Y.copy()
    if target.startswith("scaled"):
        y = y / scale
    if "log" in target:
        y = np.log1p(y)
    if method == "linear":
        model = LinearRegression()
    else:
        depth = recipe.get("depth")
        if depth not in [5, 10]:
            raise BusinessError("Độ sâu Random Forest không được hỗ trợ.")
        model = RandomForestRegressor(
            n_estimators=200,
            max_depth=depth,
            min_samples_leaf=2,
            random_state=seed,
            n_jobs=2,
            bootstrap=True,
            max_features=1.0,
        )
    raw = model.fit(train, y).predict(predict)
    if "log" in target:
        raw = np.expm1(raw)
    if target.startswith("scaled"):
        raw = raw * predict_scale
    if not np.isfinite(raw).all() or (np.abs(raw) >= 1e14).any():
        raise BusinessError("Kết quả biến đổi ngoài giới hạn lưu trữ.")
    return raw
