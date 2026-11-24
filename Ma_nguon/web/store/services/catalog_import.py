"""Import an explicitly selected subset of the anonymized source catalogue.

Source identity and photographs have separate provenance. This import never
posts inventory, imports transactions, or converts a research forecast to Q.
"""

import csv
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from django.conf import settings
from django.db import transaction

from store.pricing import rounded_selling_price

from store.models import (
    AuditEvent,
    Brand,
    Category,
    Color,
    DatasetVersion,
    ExternalSkuMap,
    ForecastUnit,
    ForecastValue,
    Product,
    Role,
    Size,
    SourceFile,
    SourceType,
    SystemGuard,
    Variant,
)
from store.services.catalog import save_catalog
from store.services.documents import BusinessError, audit, authorize

BATCH = "SOURCE_CATALOG_20261108"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def source_rows(path, keys):
    """Read source rows with the standard library; do not modify the workbook."""
    found = {}
    with ZipFile(path) as book:
        strings = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            strings = ["".join(n.itertext()) for n in root.findall(NS + "si")]
        with book.open("xl/worksheets/sheet1.xml") as sheet:
            header = None
            for _, row in ET.iterparse(sheet, events=("end",)):
                if row.tag != NS + "row":
                    continue
                cells = {}
                for cell in row.findall(NS + "c"):
                    col = "".join(c for c in cell.get("r", "") if c.isalpha())
                    value = cell.findtext(NS + "v")
                    kind = cell.get("t")
                    if kind == "s" and value is not None:
                        value = strings[int(value)]
                    elif kind == "inlineStr":
                        value = "".join(cell.find(NS + "is").itertext())
                    elif value is not None:
                        value = Decimal(value)
                    cells[col] = value
                if header is None:
                    header = cells
                else:
                    data = {name: cells.get(col) for col, name in header.items() if name}
                    if data.get("product_id") in keys:
                        if data["product_id"] in found:
                            raise BusinessError("Mã nguồn bị trùng trong danh mục gốc.")
                        found[data["product_id"]] = data
                row.clear()
    return found


def validate_bundle(
    master_file, *, collection=False, training_collection=False, training_file=None
):
    root = Path(__file__).resolve().parents[1] / "data"
    original = json.loads((root / "products.json").read_bytes())
    if training_collection:
        config_path = root / "collections/training_collection.json"
        count = 15
    elif collection:
        config_path = root / "collections/autumn_catalog.json"
        count = 12
    else:
        config_path = root / "products.json"
        count = 24
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    photos = json.loads((root / "photos.json").read_text(encoding="utf-8"))
    if collection or training_collection:
        reference_products = {row["code"]: row for row in original["products"]}
        collection_photos = []
        for product in config["products"]:
            reference = reference_products[product["reference_code"]]
            if (
                product["asset"] != reference["asset"]
                or product["source_row"]["shoe_product"] != reference["source_row"]["shoe_product"]
            ):
                raise BusinessError("Ảnh tham khảo khác dòng sản phẩm.")
            collection_photos.extend(
                dict(
                    photo,
                    product_code=product["code"],
                    source_product_id=product["source_product_id"],
                )
                for photo in photos
                if photo["product_code"] == reference["code"]
            )
        photos = collection_photos
    products = config["products"]
    keys = {p["source_product_id"] for p in products}
    if len(products) != count or len(keys) != count or len({p["code"] for p in products}) != count:
        raise BusinessError(f"Danh mục phải có {count} mã nguồn riêng biệt.")
    path = Path(master_file)
    if (
        not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != config["source_sha256"]
    ):
        raise BusinessError("Tệp danh mục nguồn thiếu hoặc sai SHA-256.")
    if training_collection:
        if not training_file:
            raise BusinessError("Cần tệp training_observed_2022.csv để đối chiếu tập huấn luyện.")
        path_train = Path(training_file)
        if hashlib.sha256(path_train.read_bytes()).hexdigest() != config["training_sha256"]:
            raise BusinessError("Tệp huấn luyện không đúng phiên bản đã đối chiếu.")
        with path_train.open(encoding="utf-8-sig", newline="") as stream:
            pairs = Counter(
                (row["product_id"], row["unit_alias"])
                for row in csv.DictReader(stream)
                if row["product_id"] in keys and row["target_month"].startswith("2022-")
            )
        for product in products:
            actual_pairs = pairs[product["source_product_id"], product["code"]]
            if actual_pairs < 6 or actual_pairs != product["training_pairs_2022"]:
                raise BusinessError(f"Mã {product['code']} không khớp số cặp huấn luyện.")
    raw = source_rows(path, keys)
    if set(raw) != keys:
        raise BusinessError("Không tìm đủ mã trong danh mục nguồn.")
    compare = [
        "product_id",
        "product_group",
        "color",
        "size",
        "gender",
        "listing_price",
        "brand_name",
        "shoe_product",
    ]
    for p in products:
        row = raw[p["source_product_id"]]
        for field in compare:
            expected = p["source_row"][field]
            equal = (
                Decimal(str(expected)) == row[field]
                if field in ["size", "listing_price"]
                else expected == row[field]
            )
            if not equal:
                raise BusinessError(f"{p['code']}: không khớp trường {field} của dữ liệu nguồn.")
        if (p["category_code"], p["color_code"], Decimal(p["size_code"]), p["listing_price"]) != (
            row["product_group"],
            row["color"],
            row["size"],
            str(p["source_row"]["listing_price"]),
        ):
            raise BusinessError("Phân nhóm, màu, cỡ hoặc giá trong cấu hình không khớp.")
        ref = p["photo_reference"]
        if (ref["group"], ref["color"], ref["gender"]) != (
            row["product_group"],
            row["color"],
            row["gender"],
        ):
            raise BusinessError("Ảnh tham khảo không khớp nhóm, màu hoặc giới tính.")
        gallery = [photo for photo in photos if photo["product_code"] == p["code"]]
        if len(gallery) != 3 or len({i["sha256"] for i in gallery}) != 3:
            raise BusinessError("Mỗi mã phải có ba ảnh khác nhau.")
        for photo in gallery:
            asset = (settings.BASE_DIR / photo["file"]).resolve()
            if not asset.is_relative_to(
                (settings.BASE_DIR / "static/shop/images/source-catalog").resolve()
            ):
                raise BusinessError("Đường dẫn ảnh nằm ngoài thư mục cho phép.")
            if (
                not asset.is_file()
                or hashlib.sha256(asset.read_bytes()).hexdigest() != photo["sha256"]
            ):
                raise BusinessError("Ảnh thiếu hoặc sai SHA-256: " + p["code"])
            if (
                photo["source_product_id"],
                photo["group"],
                photo["color_code"],
                photo["gender"],
            ) != (
                p["source_product_id"],
                row["product_group"],
                row["color"],
                row["gender"],
            ) or not photo[
                "reference_only"
            ]:
                raise BusinessError("Thông tin nguồn ảnh không hợp lệ.")
    digest = hashlib.sha256(config_bytes + json.dumps(photos, sort_keys=True).encode()).hexdigest()
    return config, digest


@transaction.atomic
def import_catalog(actor, config, digest, *, apply=False):
    actor = authorize(actor, [Role.ADMIN], lock=True)
    SystemGuard.objects.select_for_update().get(pk=1)
    ds = DatasetVersion.objects.select_for_update().get(code=config["dataset_code"])
    if (
        ds.source_type != SourceType.RESEARCH
        or not SourceFile.objects.filter(
            dataset_version=ds, sha256=config["source_sha256"]
        ).exists()
    ):
        raise BusinessError("Phiên bản dữ liệu không khớp hồ sơ nguồn nghiên cứu.")
    products = config["products"]
    batch = config.get("batch", BATCH)
    count = len(products)
    units = {
        u.external_key: u
        for u in ForecastUnit.objects.select_for_update().filter(
            dataset_version=ds, external_key__in=[p["source_product_id"] for p in products]
        )
    }
    for p in products:
        u = units.get(p["source_product_id"])
        if not u or u.label != p["code"] or u.granularity != "SKU":
            raise BusinessError("Mã định danh hoặc cấp dự báo không khớp: " + p["code"])
        if not ExternalSkuMap.objects.filter(
            forecast_unit=u, external_product_id=u.external_key
        ).exists():
            raise BusinessError("Thiếu hồ sơ mã nguồn: " + p["code"])
    if config.get("training_sha256"):
        forecasted = set(
            ForecastValue.objects.filter(
                forecast_unit__in=units.values(),
                result_status="VALID",
                run__status="SUCCEEDED",
                run__cutoff_month="2023-07-01",
                run__target_month="2023-08-01",
                run__model_result__selected_on_validation=True,
                run__model_result__experiment__dataset_version=ds,
            ).values_list("forecast_unit__external_key", flat=True)
        )
        if forecasted != set(units):
            raise BusinessError("Một hoặc nhiều mã thiếu kết quả dự báo kỳ 08/2023.")
    previous = AuditEvent.objects.filter(
        action="IMPORT_SOURCE_CATALOG", changed_fields__batch=batch
    ).first()
    if previous:
        if previous.changed_fields.get("definition_sha256") != digest:
            raise BusinessError("Đợt nhập đã tồn tại với cấu hình khác; chưa ghi đè.")
        for p in products:
            u = units[p["source_product_id"]]
            if (
                not u.internal_product_id
                or u.internal_product.code != p["code"]
                or not ExternalSkuMap.objects.filter(
                    forecast_unit=u,
                    external_product_id=u.external_key,
                    internal_variant__sku=p["sku"],
                    internal_variant__product_id=u.internal_product_id,
                ).exists()
            ):
                raise BusinessError("Liên kết đã thay đổi sau lần nhập trước; cần kiểm tra.")
        return {"status": "unchanged", "products": count, "inventory_imported": False}
    if Product.objects.filter(code__in=[p["code"] for p in products]).exists():
        raise BusinessError("Mã sản phẩm đã tồn tại; không được ghi đè.")
    if any(u.internal_product_id or u.mapping_status != "UNVERIFIED" for u in units.values()):
        raise BusinessError("Mã nguồn đã được ánh xạ; không được thay liên kết.")
    if ExternalSkuMap.objects.filter(
        forecast_unit__in=units.values(), internal_variant__isnull=False
    ).exists():
        raise BusinessError("Mã nguồn đã có biến thể nội bộ.")
    if not apply:
        return {
            "status": "dry_run",
            "products": count,
            "photos": count * 3,
            "inventory_imported": False,
        }
    before = list(
        Variant.objects.order_by("pk").values(
            "id", "sku", "selling_price", "balance__quantity", "balance__version"
        )
    )
    new_ids = []

    def lookup(model, kind, code, name):
        obj = model.objects.filter(code=code).first()
        if obj and not obj.is_active:
            raise BusinessError("Thuộc tính đã ngừng sử dụng: " + code)
        return obj or save_catalog(actor, kind, {"code": code, "name": name, "is_active": True})

    for p in products:
        category = lookup(Category, "categories", p["category_code"], p["category_name"])
        brand_name = p["source_row"]["brand_name"]
        brand = lookup(Brand, "brands", brand_name.upper(), brand_name)
        size = lookup(Size, "sizes", p["size_code"], p["size_code"])
        color = lookup(Color, "colors", p["color_code"], p["color_name"])
        product = save_catalog(
            actor,
            "products",
            dict(
                code=p["code"],
                name=p["name"],
                category=category,
                brand=brand,
                unit=p["unit"],
                is_active=True,
            ),
        )
        variant = save_catalog(
            actor,
            "variants",
            dict(
                sku=p["sku"],
                product=product,
                size=size,
                color=color,
                selling_price=rounded_selling_price(p["listing_price"]),
                low_stock_threshold=None,
                is_active=True,
            ),
        )
        new_ids.append(variant.pk)
        u = units[p["source_product_id"]]
        evidence = (
            "Đối chiếu trực tiếp Productmaster.xlsx SHA-256 "
            + config["source_sha256"]
            + "; sao chép đúng một SKU nguồn thành một sản phẩm và một biến thể. "
            "Chỉ xác minh định danh, nhóm, màu và cỡ; ảnh là ảnh tham khảo Biti’s. "
            "Chưa xác minh đơn vị quy đổi, giá hiện hành hoặc tồn kho. Nguồn giữ RESEARCH, cấp SKU."
        )
        u.internal_product = product
        u.mapping_status = "VERIFIED"
        u.mapping_evidence = evidence
        u.save(update_fields=["internal_product", "mapping_status", "mapping_evidence"])
        mapping = ExternalSkuMap.objects.select_for_update().get(
            forecast_unit=u, external_product_id=u.external_key
        )
        mapping.internal_variant = variant
        mapping.evidence = evidence
        mapping.verified_by = actor
        mapping.save(update_fields=["internal_variant", "evidence", "verified_by"])
    retired = []
    for product in Product.objects.select_for_update().filter(
        code__in=config["legacy_product_codes"], is_active=True
    ):
        save_catalog(
            actor,
            "products",
            {
                key: (False if key == "is_active" else getattr(product, key))
                for key in ["code", "name", "category", "brand", "unit", "is_active"]
            },
            product.pk,
            product.version,
        )
        retired.append(product.code)
    after = list(
        Variant.objects.exclude(pk__in=new_ids)
        .order_by("pk")
        .values("id", "sku", "selling_price", "balance__quantity", "balance__version")
    )
    if before != after:
        raise BusinessError("Biến thể hoặc số dư cũ đã thay đổi; hủy đợt nhập.")
    result = dict(
        batch=batch,
        definition_sha256=digest,
        products=count,
        variants=count,
        photos=count * 3,
        retired_product_codes=retired,
        variant_ids=new_ids,
        inventory_imported=False,
        source_type_unchanged=True,
        old_balances_preserved=True,
    )
    audit(
        actor,
        "IMPORT_SOURCE_CATALOG",
        ds,
        result,
        reason="Đồng bộ danh mục theo dữ liệu nguồn theo lựa chọn của người dùng; không nhập tồn hoặc giao dịch.",
    )
    return {"status": "imported", **result}
