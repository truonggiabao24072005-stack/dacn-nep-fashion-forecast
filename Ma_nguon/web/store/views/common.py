from decimal import Decimal
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import render

from store.models import Category, SystemGuard, Variant
from store.services.customers import current_customer
from store.services.documents import authorize
from store.services.location import current_location, location_details
from store.services.orders import active_variants
from store.services.pickup import with_available_stock
from store.services.presentation import presentation
from store.validation import positive_identifier


def role_required(*roles):
    def outer(fn):
        @login_required
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            request.user = authorize(request.user, roles)
            return fn(request, *args, **kwargs)

        return wrapped

    return outer


def show_error(form, exc):
    if isinstance(exc, ValidationError):
        for message in exc.messages:
            form.add_error(None, message)
    elif isinstance(exc, IntegrityError):
        form.add_error(
            None, "Mã hoặc tổ hợp đã tồn tại, hoặc dữ liệu đã thay đổi. Hãy kiểm tra và tải lại."
        )
    else:
        form.add_error(None, str(exc))


CART_SESSION_KEY = "nep_cart"


def cart_data(request):
    raw = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(raw, dict):
        return {}
    clean = {}
    for key, value in list(raw.items())[:30]:
        identifier = positive_identifier(key)
        if identifier is not None and type(value) is int and 1 <= value <= 99:
            clean[str(identifier)] = value
    return clean


def common(request):
    location = current_location()
    return {
        "shop_categories": Category.objects.filter(
            is_active=True, product__is_active=True
        ).distinct(),
        "bag_count": sum(cart_data(request).values()),
        "shop_demo": SystemGuard.objects.filter(pk=1, data_mode="DEMO").exists(),
        "shop_customer": current_customer(request),
        "shop_location": (
            location_details(location.address, location.is_example) if location else None
        ),
    }


def shop_render(request, name, context=None):
    return render(request, "shop/" + name + ".html", {**common(request), **(context or {})})


def cart_snapshot(request):
    data = cart_data(request)
    variants = {
        str(v.pk): v
        for v in with_available_stock(
            Variant.objects.select_related(
                "product", "size", "color", "balance", "product__category", "product__brand"
            ).filter(pk__in=data)
        )
    }
    valid_ids = set(active_variants().filter(pk__in=data).values_list("pk", flat=True))
    rows = []
    total = Decimal(0)
    ready = bool(data)
    for vid, n in data.items():
        v = variants.get(vid)
        if not v:
            rows.append(
                {
                    "variant_id": vid,
                    "quantity": n,
                    "missing": True,
                    "error": "Mặt hàng không còn trong danh mục.",
                }
            )
            ready = False
            continue
        error = ""
        if v.pk not in valid_ids:
            error = "Biến thể này đã ngừng bán."
        elif v.available_stock < n:
            error = f"Hiện chỉ còn {v.available_stock} sản phẩm. Vui lòng cập nhật số lượng."
        rows.append(
            {
                "variant_id": vid,
                "variant": v,
                "quantity": n,
                "line_total": n * v.selling_price,
                **presentation(v.product),
                "error": error,
            }
        )
        total += n * v.selling_price
        if error:
            ready = False
    if not 0 < total < 10**18:
        ready = False
    return {"rows": rows, "total": total, "ready": ready, "count": sum(data.values())}
