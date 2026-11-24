from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from store.services.documents import BusinessError, quantity
from store.services.orders import active_variants
from store.validation import positive_identifier
from store.views.common import CART_SESSION_KEY, cart_data, cart_snapshot, shop_render


@require_POST
def cart_action(request):
    data = cart_data(request)
    identifier = positive_identifier(request.POST.get("variant_id", ""))
    vid = str(identifier) if identifier is not None else ""
    action = request.POST.get("action", "add")
    if action == "remove":
        data.pop(vid, None)
        request.session[CART_SESSION_KEY] = data
        messages.success(request, "Đã bỏ sản phẩm khỏi giỏ.")
        return redirect("shop_cart")
    try:
        if identifier is None:
            raise BusinessError("Chưa chọn được mặt hàng hợp lệ.")
        v = active_variants().filter(pk=identifier).first()
        if not v:
            raise BusinessError("Sản phẩm không còn mở bán. Vui lòng chọn mặt hàng khác.")
        n = quantity(request.POST.get("quantity", ""))
        if action == "add":
            n += data.get(vid, 0)
        elif action != "update":
            raise BusinessError("Thao tác giỏ hàng không hợp lệ.")
        if n > 99:
            raise BusinessError("Mỗi biến thể nhận tối đa 99 sản phẩm trong một giỏ.")
        if n > v.available_stock:
            raise BusinessError(
                f"{v.product.name} · {v.size.name}/{v.color.name}: hiện còn {v.available_stock} sản phẩm."
            )
        if vid not in data and len(data) >= 30:
            raise BusinessError("Giỏ hàng đã có đủ 30 mặt hàng.")
        data[vid] = n
        request.session[CART_SESSION_KEY] = data
        messages.success(request, "Đã cập nhật giỏ hàng của bạn.")
    except BusinessError as exc:
        messages.error(request, str(exc))
    return redirect("shop_cart")


@never_cache
def cart(request):
    return shop_render(
        request, "cart/detail", {"title": "Giỏ hàng của bạn", **cart_snapshot(request)}
    )
