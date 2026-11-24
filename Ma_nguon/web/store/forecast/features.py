"""Chuyển lỗi huấn luyện thành thông báo nghiệp vụ của website."""

from store.forecast.training import fit_recipe as train_recipe
from store.services.documents import BusinessError


def fit_recipe(recipe, X, Y, future, seed=42):
    try:
        return train_recipe(recipe, X, Y, future, seed)
    except ValueError as exc:
        raise BusinessError(str(exc)) from exc
