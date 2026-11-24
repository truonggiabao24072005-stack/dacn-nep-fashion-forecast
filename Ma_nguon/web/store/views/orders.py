from uuid import uuid4

from django.contrib import messages
from django.core import signing
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from store.forms.checkout import CheckoutForm
from store.models import Role, WebOrder
from store.services.customers import account_owner, current_customer
from store.services.documents import BusinessError
from store.services.location import location_details
from store.services.orders import accept_order, cancel_order, submit_order
from store.views.common import (
    CART_SESSION_KEY,
    cart_data,
    cart_snapshot,
    role_required,
    shop_render,
)

CHECKOUT_SESSION_KEYS = "nep_checkout_keys"


CHECKOUT_QUOTE_SALT = "nep.checkout.v1"


def owner(request, create=False):
    customer = current_customer(request)
    if customer:
        return account_owner(customer)
    if not request.session.session_key:
        if not create:
            return ""
        request.session.save()
    return salted_hmac(
        "nep.guest.order", request.session.session_key, algorithm="sha256"
    ).hexdigest()


def read_quote(token):
    try:
        rows = signing.loads(token, salt=CHECKOUT_QUOTE_SALT, max_age=3600)
        if not isinstance(rows, list) or not rows or len(rows) > 30:
            raise ValueError()
        for row in rows:
            if (
                not isinstance(row, list)
                or len(row) != 3
                or type(row[0]) is not int
                or type(row[1]) is not int
                or not isinstance(row[2], str)
            ):
                raise ValueError()
        return rows
    except (signing.BadSignature, ValueError, TypeError):
        raise BusinessError(
            "Giỏ hàng đã hết thời gian xác nhận hoặc bị thay đổi. Vui lòng mở lại trang đặt hàng."
        )


@never_cache
def checkout(request):
    snapshot = cart_snapshot(request)
    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            try:
                values = form.cleaned_data
                key = values["request_key"]
                if str(key) not in request.session.get(CHECKOUT_SESSION_KEYS, []):
                    raise BusinessError("Phiên đặt hàng không hợp lệ. Vui lòng mở lại giỏ hàng.")
                quote = read_quote(values["quote"])
                who = owner(request)
                previous = WebOrder.objects.filter(request_key=key, owner_hash=who).exists()
                if not previous and sorted((str(r[0]), r[1]) for r in quote) != sorted(
                    cart_data(request).items()
                ):
                    raise BusinessError("Giỏ hàng vừa thay đổi. Vui lòng mở lại để kiểm tra.")
                order, created = submit_order(
                    who, key, quote, values, account=current_customer(request)
                )
                if created:
                    request.session[CART_SESSION_KEY] = {}
                return redirect("shop_order", pk=order.pk)
            except BusinessError as exc:
                form.add_error(None, str(exc))
    else:
        if not snapshot["ready"]:
            messages.error(
                request, "Vui lòng kiểm tra sản phẩm và số lượng trong giỏ trước khi đặt."
            )
            return redirect("shop_cart")
        owner(request, True)
        key = uuid4()
        keys = request.session.get(CHECKOUT_SESSION_KEYS, [])
        request.session[CHECKOUT_SESSION_KEYS] = (keys + [str(key)])[-8:]
        quote = [
            [int(r["variant_id"]), r["quantity"], str(r["variant"].selling_price)]
            for r in snapshot["rows"]
        ]
        customer = current_customer(request)
        profile = getattr(customer, "customer_profile", None) if customer else None
        form = CheckoutForm(
            initial={
                "request_key": key,
                "quote": signing.dumps(quote, salt=CHECKOUT_QUOTE_SALT, compress=True),
                "customer_name": customer.full_name if customer else "",
                "phone": profile.phone if profile else "",
            }
        )
    return shop_render(
        request, "cart/checkout", {"title": "Thông tin đặt hàng", "form": form, **snapshot}
    )


@never_cache
def order_detail(request, pk):
    order = get_object_or_404(
        owned_orders(request).select_related("sale", "handled_by").prefetch_related("lines"),
        pk=pk,
    )
    from store.services.vnpay import gateway_available

    return shop_render(
        request,
        "orders/detail",
        {
            "title": "Đơn hàng " + order.code,
            "order": order,
            "gateway_available": gateway_available(),
            "order_pickup_location": location_details(
                order.pickup_address, order.pickup_address_is_example
            ),
        },
    )


@never_cache
def orders(request):
    return shop_render(
        request,
        "orders/list",
        {
            "title": "Đơn hàng của bạn",
            "orders": owned_orders(request).select_related("sale")[:30],
        },
    )


def owned_orders(request):
    customer = current_customer(request)
    return (
        WebOrder.objects.with_lifecycle().filter(account=customer)
        if customer
        else WebOrder.objects.with_lifecycle().filter(
            owner_hash=owner(request), account__isnull=True
        )
    )


@require_POST
def customer_cancel(request, pk):
    get_object_or_404(owned_orders(request), pk=pk)
    try:
        cancel_order(
            pk,
            request.POST.get("version"),
            owner=owner(request),
            account=current_customer(request),
        )
        messages.success(request, "Đã hủy yêu cầu đặt hàng của bạn.")
    except BusinessError as exc:
        messages.error(request, str(exc))
    return redirect("shop_order", pk=pk)


@role_required(Role.ADMIN, Role.SALES)
def incoming(request):
    status = request.GET.get("status", "PENDING")
    qs = WebOrder.objects.with_lifecycle().select_related("sale", "handled_by")
    if status in WebOrder.LIFECYCLE_LABELS:
        qs = qs.filter(_db_lifecycle_status=status)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "store/orders/list.html",
        {
            "title": "Đơn khách đặt trên Web",
            "page": page,
            "selected_status": status,
            "statuses": WebOrder.LIFECYCLE_LABELS.items(),
        },
    )


@role_required(Role.ADMIN, Role.SALES)
def incoming_detail(request, pk):
    order = get_object_or_404(
        WebOrder.objects.with_lifecycle()
        .select_related("sale", "handled_by")
        .prefetch_related("lines__variant__balance"),
        pk=pk,
    )
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "accept":
                order = accept_order(
                    request.user,
                    pk,
                    request.POST.get("version"),
                    request.POST.get("price_ack") == "on",
                    hold_pickup=True,
                )
                messages.success(
                    request,
                    (
                        "Đã tiếp nhận đơn. Khách có thể mở trang đơn để thanh toán VNPAY."
                        if order.payment_preference == "VNPAY"
                        else "Đã tiếp nhận đơn. Chỉ xác nhận bán khi nhận đủ tiền tại cửa hàng."
                    ),
                )
                return redirect("document", kind="sale", pk=order.sale_id)
            elif action == "no_show":
                from store.services.pickup import close_missed_pickup

                close_missed_pickup(request.user, order.pk)
                messages.success(request, "Đã đóng đơn quá hạn nhận hàng.")
                return redirect("web_order", pk=pk)
            elif action in ("ship", "deliver"):
                from store.services.vnpay import update_shipment

                update_shipment(pk, action, request.POST.get("tracking", ""))
                return redirect("web_order", pk=pk)
            elif action == "cancel":
                cancel_order(
                    pk,
                    request.POST.get("version"),
                    actor=request.user,
                    reason=request.POST.get("reason", ""),
                )
            else:
                raise BusinessError("Thao tác không hợp lệ.")
            messages.success(request, "Đã hủy yêu cầu và lưu lý do.")
            return redirect("web_order", pk=pk)
        except BusinessError as exc:
            messages.error(request, str(exc))
    from django.utils import timezone

    return render(
        request,
        "store/orders/detail.html",
        {
            "title": order.code,
            "order": order,
            "pickup_overdue": bool(
                order.pickup_expires_at and order.pickup_expires_at <= timezone.now()
            ),
        },
    )
