from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from store.models import (
    STAFF_ROLES,
    AdjustmentLine,
    Brand,
    Category,
    Color,
    Customer,
    Product,
    ReceiptLine,
    ReplenishmentPolicy,
    ReplenishmentSuggestion,
    Role,
    SaleLine,
    Size,
    Supplier,
    SystemGuard,
    User,
    Variant,
    WebOrderLine,
    timezone,
)
from store.services.documents import BusinessError, audit, authorize, quantity

CATALOGS = {
    "products": (Product, "Sản phẩm", ["code", "name", "category", "brand", "unit", "is_active"]),
    "variants": (
        Variant,
        "Biến thể",
        ["sku", "product", "size", "color", "selling_price", "low_stock_threshold", "is_active"],
    ),
    "categories": (Category, "Danh mục", ["code", "name", "is_active"]),
    "brands": (Brand, "Thương hiệu", ["code", "name", "is_active"]),
    "sizes": (Size, "Kích thước", ["code", "name", "is_active"]),
    "colors": (Color, "Màu sắc", ["code", "name", "is_active"]),
    "suppliers": (Supplier, "Nhà cung cấp", ["code", "name", "phone", "address", "is_active"]),
    "customers": (Customer, "Khách hàng", ["code", "name", "phone", "note", "is_active"]),
}


def catalog_roles(kind, write=False):
    if kind == "customers":
        return [Role.ADMIN, Role.SALES]
    if kind == "suppliers":
        return [Role.ADMIN, Role.WAREHOUSE]
    return [Role.ADMIN] if write else STAFF_ROLES


@transaction.atomic
def save_catalog(actor, kind, values, pk=None, version=None):
    actor = authorize(actor, catalog_roles(kind, True), lock=True)
    model, _, fields = CATALOGS[kind]
    if kind == "variants":
        product_ids = {values["product"].pk}
        if pk:
            product_ids.update(Variant.objects.filter(pk=pk).values_list("product_id", flat=True))
        list(Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk"))
    obj = model.objects.select_for_update().get(pk=pk) if pk else model()
    if pk and str(obj.version) != str(version):
        raise BusinessError("Hồ sơ đã thay đổi. Hãy tải lại trước khi lưu.")
    before = {f: str(getattr(obj, f)) for f in fields} if pk else {}
    if kind == "variants" and pk:
        used = (
            obj.stock_entries.exists()
            or SaleLine.objects.filter(variant=obj).exists()
            or ReceiptLine.objects.filter(variant=obj).exists()
            or AdjustmentLine.objects.filter(variant=obj).exists()
            or WebOrderLine.objects.filter(variant=obj).exists()
        )
        if used and any(
            str(getattr(obj, f)) != str(values[f]) for f in ["sku", "product", "size", "color"]
        ):
            raise BusinessError(
                "Biến thể đã được tham chiếu. Không được đổi mã, sản phẩm, kích thước hoặc màu."
            )
    if (
        kind == "products"
        and pk
        and obj.variants.filter(stock_entries__isnull=False).exists()
        and obj.unit != values["unit"]
    ):
        raise BusinessError("Sản phẩm đã có sổ kho; không được đổi đơn vị đếm.")
    if pk and kind not in ["customers", "suppliers"]:
        key = "sku" if kind == "variants" else "code"
        if getattr(obj, key).strip().upper() != str(values[key]).strip().upper():
            raise BusinessError(
                "Mã định danh được giữ nguyên. Hãy tạo hồ sơ mới nếu cần một mã khác."
            )
    for f in fields:
        setattr(obj, f, values[f])
    if hasattr(obj, "code"):
        obj.code = obj.code.strip().upper()
    if hasattr(obj, "sku"):
        obj.sku = obj.sku.strip().upper()
    if hasattr(obj, "name") and not obj.name.strip():
        raise BusinessError("Tên không được chỉ gồm khoảng trắng.")
    if (
        kind == "products"
        and obj.is_active
        and not (obj.category.is_active and obj.brand.is_active)
    ):
        raise BusinessError("Danh mục và thương hiệu phải đang sử dụng.")
    if (
        kind == "variants"
        and obj.is_active
        and not all([obj.product.is_active, obj.size.is_active, obj.color.is_active])
    ):
        raise BusinessError("Sản phẩm, kích thước và màu phải đang sử dụng.")
    if pk:
        obj.version += 1
    obj.full_clean()
    obj.save()
    after = {f: str(getattr(obj, f)) for f in fields}
    audit(
        actor,
        "UPDATE_CATALOG" if pk else "CREATE_CATALOG",
        obj,
        {
            f: {"before": before.get(f), "after": value}
            for f, value in after.items()
            if before.get(f) != value
        },
    )
    return obj


@transaction.atomic
def save_user(actor, values, pk=None, version=None):
    SystemGuard.objects.get_or_create(pk=1)
    guard = SystemGuard.objects.select_for_update().get(pk=1)
    actor = authorize(actor, [Role.ADMIN], lock=True)
    target = User.objects.select_for_update().get(pk=pk) if pk else User()
    if values["role"] not in STAFF_ROLES or (pk and target.role not in STAFF_ROLES):
        raise BusinessError("Chức năng này chỉ cấp và sửa tài khoản nhân viên.")
    if pk and str(target.version) != str(version):
        raise BusinessError("Tài khoản đã thay đổi; cần tải lại hồ sơ.")
    if (
        pk
        and target.role == Role.ADMIN
        and target.is_active
        and (values["role"] != Role.ADMIN or not values["is_active"])
    ):
        if not User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk=target.pk).exists():
            raise BusinessError("Không được khóa hoặc hạ quyền quản trị viên hoạt động cuối cùng.")
    old = {"role": target.role, "is_active": target.is_active} if pk else {}
    target.username = values["username"].strip().lower()
    target.full_name = values["full_name"].strip()
    target.role = values["role"]
    target.is_active = values["is_active"]
    password = values.get("new_password")
    if not pk and not password:
        raise BusinessError("Cần đặt mật khẩu cho tài khoản mới.")
    if password:
        validate_password(password, target)
        target.set_password(password)
    if pk:
        target.version += 1
    target.full_clean()
    target.save()
    guard.version += 1
    guard.save(update_fields=["version"])
    audit(
        actor,
        "UPDATE_USER" if pk else "CREATE_USER",
        target,
        {
            "before": old,
            "role": target.role,
            "is_active": target.is_active,
            "password_changed": bool(password),
        },
    )
    return target


@transaction.atomic
def set_safety_stock(actor, product_id, count, *, expected_policy_id=None):
    actor = authorize(actor, [Role.ADMIN], lock=True)
    product = Product.objects.select_for_update().get(pk=product_id)
    count = quantity(count, zero=True)
    current = ReplenishmentPolicy.objects.filter(product=product, effective_to__isnull=True).first()
    if expected_policy_id is not None and str(current.pk if current else 0) != str(
        expected_policy_id
    ):
        raise BusinessError(
            "Tồn an toàn đã thay đổi. Hãy tải lại trang và đối chiếu trước khi lưu."
        )
    now = timezone.now()
    ReplenishmentPolicy.objects.filter(product=product, effective_to__isnull=True).update(
        effective_to=now
    )
    policy = ReplenishmentPolicy.objects.create(
        product=product, safety_stock_qty=count, effective_from=now, updated_by=actor
    )
    ReplenishmentSuggestion.objects.filter(product=product, status="CURRENT").update(status="STALE")
    audit(actor, "SET_SAFETY_STOCK", product, {"quantity": count})
    return policy
