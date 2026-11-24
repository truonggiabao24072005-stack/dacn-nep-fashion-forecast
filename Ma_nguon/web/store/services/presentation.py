"""Ảnh và mô tả của danh mục hiện hành; giá và tồn lấy từ PostgreSQL."""

import json
from pathlib import Path

SOURCE_CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "data/products.json").read_text(encoding="utf-8")
)
ADDITIONAL_PRODUCTS = [
    row
    for filename in ("autumn_catalog.json", "training_collection.json")
    for row in json.loads(
        (Path(__file__).resolve().parents[1] / "data/collections" / filename).read_text(
            encoding="utf-8"
        )
    )["products"]
]
COLLECTION_CODES = [row["code"] for row in ADDITIONAL_PRODUCTS]
SOURCE_PRODUCTS = {row["code"]: row for row in [*SOURCE_CATALOG["products"], *ADDITIONAL_PRODUCTS]}
PHOTO_CREDITS = json.loads(
    (Path(__file__).resolve().parents[1] / "data/photos.json").read_text(encoding="utf-8")
)
PHOTO_BY_ASSET = {row["asset"]: row for row in PHOTO_CREDITS}
PHOTO_GALLERIES = {row["asset"]: [row] for row in PHOTO_CREDITS if not row.get("gallery_for")}
for row in PHOTO_CREDITS:
    if row.get("gallery_for") in PHOTO_GALLERIES:
        PHOTO_GALLERIES[row["gallery_for"]].append(row)

COLOR_HEX = {row["color_code"]: row["color_hex"] for row in SOURCE_PRODUCTS.values()}


def presentation(product):
    source = SOURCE_PRODUCTS.get(product.code)
    asset = source["asset"] if source else None
    photo = PHOTO_BY_ASSET.get(asset, {})
    return {
        "image": photo.get("static_path", ""),
        "description": (
            source["description"]
            if source
            else ("Chọn kích thước và màu để xem giá cùng tình trạng còn hàng của từng biến thể.")
        ),
        "photo": photo,
        "gallery": PHOTO_GALLERIES.get(asset, []),
        "source": source,
    }
