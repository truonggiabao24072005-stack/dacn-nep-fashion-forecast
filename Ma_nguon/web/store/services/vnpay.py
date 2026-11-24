import hashlib
import hmac
from datetime import timedelta
from ipaddress import ip_address
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from store.models import GatewayPayment, SaleOrder, Status, WebOrder
from store.services.documents import BusinessError, _lock_stock, confirm_document

SANDBOX = "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
LIVE = "https://pay.vnpay.vn/vpcpay.html"
VN_TIME = ZoneInfo("Asia/Ho_Chi_Minh")


def gateway_available():
    return all((settings.VNPAY_TMN_CODE, settings.VNPAY_SECRET, settings.VNPAY_RETURN_URL))


def signed_query(fields):
    query = urlencode(sorted(fields.items()))
    signature = hmac.new(settings.VNPAY_SECRET.encode(), query.encode(), hashlib.sha512)
    return query, signature.hexdigest()


def verified_payload(params):
    if not gateway_available():
        return None
    if any(len(params.getlist(key)) != 1 for key in params if key.startswith("vnp_")):
        return None
    fields = {key: value for key, value in params.items() if key.startswith("vnp_")}
    signature = fields.pop("vnp_SecureHash", "")
    fields.pop("vnp_SecureHashType", None)
    _, expected = signed_query(fields)
    if (
        not hmac.compare_digest(signature, expected)
        or fields.get("vnp_TmnCode") != settings.VNPAY_TMN_CODE
    ):
        return None
    return fields


@transaction.atomic
def payment_url(order, remote_ip):
    if not gateway_available() or order.payment_preference != "VNPAY" or not order.sale_id:
        raise BusinessError("Đơn chưa sẵn sàng thanh toán qua VNPAY.")
    sale = SaleOrder.objects.select_for_update().get(pk=order.sale_id)
    if sale.status != Status.DRAFT:
        raise BusinessError("Đơn bán này đã được xử lý.")
    existing = GatewayPayment.objects.filter(order=order).first()
    if existing and (
        existing.status != "WAITING"
        or existing.amount != sale.total_amount
        or existing.created_at + timedelta(minutes=15) <= timezone.now()
    ):
        raise BusinessError("Lượt thanh toán đã kết thúc. Vui lòng liên hệ cửa hàng để đối chiếu.")
    lines = list(sale.lines.all())
    if {line.variant_id: line.quantity for line in lines} != dict(
        order.lines.values_list("variant_id", "quantity")
    ):
        raise BusinessError("Các mặt hàng trong đơn đã thay đổi. Vui lòng liên hệ cửa hàng.")
    if not lines or not 0 < sale.total_amount < 10**10:
        raise BusinessError("Giá trị đơn ngoài giới hạn thanh toán.")
    variants, balances = _lock_stock([line.variant_id for line in lines])
    if any(
        balances[line.variant_id].quantity < line.quantity
        or variants[line.variant_id].selling_price != line.unit_price
        for line in lines
    ):
        raise BusinessError("Giá hoặc tồn kho đã thay đổi. Vui lòng liên hệ cửa hàng.")
    try:
        client_ip = str(ip_address(remote_ip))
    except ValueError:
        raise BusinessError("Địa chỉ mạng không hợp lệ.") from None
    payment = existing or GatewayPayment.objects.create(
        order=order, amount=int(sale.total_amount), client_ip=client_ip
    )
    issued = payment.created_at.astimezone(VN_TIME)
    fields = {
        "vnp_Version": "2.1.0",
        "vnp_Command": "pay",
        "vnp_TmnCode": settings.VNPAY_TMN_CODE,
        "vnp_Amount": str(payment.amount * 100),
        "vnp_CurrCode": "VND",
        "vnp_CreateDate": issued.strftime("%Y%m%d%H%M%S"),
        "vnp_ExpireDate": (issued + timedelta(minutes=15)).strftime("%Y%m%d%H%M%S"),
        "vnp_IpAddr": payment.client_ip,
        "vnp_Locale": "vn",
        "vnp_OrderInfo": f"Thanh toan don {order.code}",
        "vnp_OrderType": "other",
        "vnp_ReturnUrl": settings.VNPAY_RETURN_URL,
        "vnp_TxnRef": payment.pk.hex,
    }
    query, signature = signed_query(fields)
    return f"{SANDBOX if settings.VNPAY_SANDBOX else LIVE}?{query}&vnp_SecureHash={signature}"


@transaction.atomic
def record_notification(fields):
    try:
        payment = GatewayPayment.objects.select_for_update().get(pk=fields.get("vnp_TxnRef", ""))
    except (GatewayPayment.DoesNotExist, ValueError, ValidationError):
        return "01"
    if fields.get("vnp_Amount") != str(payment.amount * 100):
        return "04"
    if payment.status != "WAITING":
        return "02"
    if fields.get("vnp_ResponseCode") != "00" or fields.get("vnp_TransactionStatus") != "00":
        payment.status = "FAILED"
        payment.save(update_fields=["status"])
        return "00"
    reference = fields.get("vnp_TransactionNo", "")
    if not reference.isascii() or not reference.isdigit() or not 0 < len(reference) <= 32:
        return "99"
    payment.provider_reference = reference
    payment.status = "REVIEW"
    try:
        with transaction.atomic():
            payment.save(update_fields=["status", "provider_reference"])
    except IntegrityError:
        return "99"
    order = payment.order
    try:
        with transaction.atomic():
            confirm_document(
                order.handled_by,
                "sale",
                order.sale_id,
                order.sale.version,
                payment.pk,
                {"method": "VNPAY", "reference": reference},
            )
    except BusinessError:
        return "00"
    payment.status = "POSTED"
    payment.save(update_fields=["status"])
    return "00"


@transaction.atomic
def update_shipment(pk, action, tracking):
    order = WebOrder.objects.select_for_update().get(pk=pk)
    if not order.delivery_address or order.lifecycle_status != "COMPLETED":
        raise BusinessError("Chỉ cập nhật giao hàng cho đơn đã ghi sổ.")
    if action == "ship" and not order.shipment_status:
        tracking = tracking.strip()
        if not tracking or len(tracking) > 100 or any(ord(c) < 32 for c in tracking):
            raise BusinessError("Nhập mã vận đơn hợp lệ.")
        order.tracking_number = tracking
        order.shipment_status = "SHIPPED"
    elif action == "deliver" and order.shipment_status == "SHIPPED":
        order.shipment_status = "DELIVERED"
    else:
        raise BusinessError("Trạng thái giao hàng đã thay đổi.")
    order.save(update_fields=["tracking_number", "shipment_status"])
