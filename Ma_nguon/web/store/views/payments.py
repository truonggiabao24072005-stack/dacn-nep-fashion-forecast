from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from store.models import GatewayPayment
from store.services.documents import BusinessError
from store.services.vnpay import payment_url, record_notification, verified_payload
from store.views.orders import owned_orders


@require_POST
@never_cache
def pay(request, pk):
    order = get_object_or_404(owned_orders(request), pk=pk)
    try:
        return redirect(payment_url(order, request.META.get("REMOTE_ADDR", "")))
    except BusinessError as exc:
        messages.error(request, str(exc))
        return redirect("shop_order", pk=pk)


@require_GET
@never_cache
def return_to_order(request):
    fields = verified_payload(request.GET)
    if fields:
        try:
            payment = GatewayPayment.objects.filter(pk=fields.get("vnp_TxnRef", "")).first()
        except (ValueError, ValidationError):
            payment = None
        if payment and owned_orders(request).filter(pk=payment.order_id).exists():
            return redirect("shop_order", pk=payment.order_id)
    return redirect("shop_orders")


@require_GET
@never_cache
def notify(request):
    fields = verified_payload(request.GET)
    code = record_notification(fields) if fields else "97"
    messages_by_code = {
        "00": "Confirm Success",
        "01": "Order not found",
        "02": "Order already confirmed",
        "04": "Invalid amount",
        "97": "Invalid signature",
        "99": "Invalid transaction",
    }
    return JsonResponse({"RspCode": code, "Message": messages_by_code[code]})
