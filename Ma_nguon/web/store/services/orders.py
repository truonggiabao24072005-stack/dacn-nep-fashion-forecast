import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from store.models import Customer, Role, User, Variant, WebGuestOwner, WebOrder, WebOrderLine
from store.services.documents import (
    BusinessError,
    _lock_stock,
    audit,
    authorize,
    code,
    create_document,
    quantity,
    set_line,
)
from store.services.location import current_location
from store.services.pickup import held_quantities, with_available_stock


def active_variants():
    variants = Variant.objects.select_related(
        "product__category", "product__brand", "size", "color", "balance"
    ).filter(
        is_active=True,
        product__is_active=True,
        product__category__is_active=True,
        product__brand__is_active=True,
        size__is_active=True,
        color__is_active=True,
        selling_price__gt=0,
    )
    return with_available_stock(variants)


from store.services.payment_preferences import normalise_payment_method
from store.services.vnpay import gateway_available


def fingerprint(owner, quote, contact, *, legacy=False):
    payload = {
        "owner": owner,
        "quote": quote,
        "name": contact["customer_name"],
        "phone": contact["phone"],
        "note": contact.get("note", ""),
    }
    if not legacy:
        payload["payment_method"] = normalise_payment_method(contact.get("payment_method", "CASH"))
    if contact.get("delivery_address"):
        payload["delivery_address"] = contact["delivery_address"]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@transaction.atomic
def submit_order(owner, key, quote, contact, *, account=None):
    try:
        preference = normalise_payment_method(contact.get("payment_method", "CASH"))
    except ValueError as exc:
        raise BusinessError(str(exc)) from None
    address = contact.get("delivery_address", "").strip()
    contact = {**contact, "delivery_address": address}
    if address and (
        preference != "VNPAY" or len(address) < 10 or len(address) > 350 or "\x00" in address
    ):
        raise BusinessError("Địa chỉ giao hàng cần từ 10 đến 350 ký tự và thanh toán qua VNPAY.")
    if preference == "VNPAY" and not gateway_available():
        raise BusinessError("Thanh toán trực tuyến chưa mở.")
    if account is not None:
        from store.services.customers import account_owner

        account = (
            User.objects.select_for_update()
            .filter(pk=account.pk, is_active=True, role=Role.CUSTOMER)
            .first()
        )
        if not account or owner != account_owner(account):
            raise BusinessError("Tài khoản không còn hợp lệ. Vui lòng đăng nhập lại.")
    else:
        WebGuestOwner.objects.get_or_create(owner_hash=owner)
        identity = WebGuestOwner.objects.select_for_update().get(pk=owner)
        if identity.account_id:
            raise BusinessError(
                "Phiên đặt hàng đã chuyển sang tài khoản. Vui lòng tải lại trang đặt hàng."
            )
    digest = fingerprint(owner, quote, contact)
    previous = WebOrder.objects.filter(request_key=key).first()
    if previous:
        legacy_match = (
            previous.payment_preference == "UNSPECIFIED"
            and "payment_method" not in contact
            and previous.payload_hash == fingerprint(owner, quote, contact, legacy=True)
        )
        if (
            previous.account_id != (account.pk if account else None)
            or previous.owner_hash != owner
            or (previous.payload_hash != digest and not legacy_match)
        ):
            raise BusinessError(
                "Yêu cầu đã thay đổi. Vui lòng xem lại giỏ và gửi bằng một lượt mới."
            )
        return previous, False
    if not quote or len(quote) > 30:
        raise BusinessError("Giỏ hàng cần có từ 1 đến 30 mặt hàng.")
    ids = [int(row[0]) for row in quote]
    if len(set(ids)) != len(ids):
        raise BusinessError("Giỏ hàng không hợp lệ.")
    variants = {v.pk: v for v in active_variants().filter(pk__in=ids)}
    held = held_quantities(ids)
    total = Decimal(0)
    lines = []
    for vid, qty, price in quote:
        v = variants.get(int(vid))
        n = quantity(qty)
        if n > 99 or not v:
            raise BusinessError(
                "Có mặt hàng đã ngừng bán hoặc số lượng không hợp lệ. Hãy kiểm tra lại giỏ."
            )
        if v.balance.quantity - held.get(v.pk, 0) < n:
            raise BusinessError(
                f"{v.product.name} · {v.size.name}/{v.color.name}: hiện không đủ hàng. Hãy cập nhật giỏ."
            )
        if v.selling_price != Decimal(str(price)):
            raise BusinessError("Giá sản phẩm vừa thay đổi. Vui lòng xem lại giỏ trước khi đặt.")
        total += n * v.selling_price
        lines.append(
            WebOrderLine(
                variant=v,
                quantity=n,
                unit_price=v.selling_price,
                name_snapshot=v.product.name,
                sku_snapshot=v.sku,
                variant_snapshot=f"{v.size.name} / {v.color.name}",
            )
        )
    if not 0 < total < 10**18:
        raise BusinessError("Giá trị giỏ nằm ngoài giới hạn cho phép.")
    location = None if address else current_location()
    order, created = WebOrder.objects.get_or_create(
        request_key=key,
        defaults={
            "code": code("DH"),
            "owner_hash": owner,
            "account": account,
            "payload_hash": digest,
            "customer_name": contact["customer_name"],
            "phone": contact["phone"],
            "note": contact.get("note", ""),
            "payment_preference": preference,
            "delivery_address": address,
            "pickup_address": location.address if location else "",
            "pickup_address_is_example": location.is_example if location else False,
            "total_amount": total,
        },
    )
    if not created:
        if (
            order.account_id != (account.pk if account else None)
            or order.owner_hash != owner
            or order.payload_hash != digest
        ):
            raise BusinessError("Mã yêu cầu đã được sử dụng với nội dung khác.")
        return order, False
    for line in lines:
        line.order = order
    WebOrderLine.objects.bulk_create(lines)
    return order, True


@transaction.atomic
def accept_order(actor, pk, version, price_ack=False, *, hold_pickup=False):
    actor = authorize(actor, [Role.ADMIN, Role.SALES], lock=True)
    order = WebOrder.objects.select_for_update().get(pk=pk)
    if order.status == "ACCEPTED":
        if order.handled_by_id == actor.pk or actor.role == Role.ADMIN:
            return order
        raise BusinessError("Một nhân viên khác đã tiếp nhận đơn này.")
    if order.status != "PENDING" or str(order.version) != str(version):
        raise BusinessError("Đơn đã thay đổi. Vui lòng tải lại để kiểm tra.")
    lines = list(order.lines.all())
    variants, balances = _lock_stock([line.variant_id for line in lines])
    held = held_quantities(balances)
    for line in lines:
        v = variants[line.variant_id]
        if balances[v.pk].quantity - held.get(v.pk, 0) < line.quantity:
            raise BusinessError(f"{v.sku}: chưa đủ tồn để tiếp nhận. Cần đối chiếu lại với khách.")
        if v.selling_price <= 0:
            raise BusinessError("Biến thể chưa có giá bán hợp lệ.")
        if v.selling_price != line.unit_price and not price_ack:
            raise BusinessError(
                "Giá hiện tại khác giá khách đã xem. Cần xác nhận đã thống nhất giá mới với khách."
            )
    customer = Customer.objects.create(
        code=code("KH"),
        name=order.customer_name,
        phone=order.phone,
        note="Hồ sơ từ yêu cầu " + order.code,
    )
    sale = create_document(actor, "sale", {"customer": customer})
    for line in lines:
        sale = set_line(
            actor, "sale", sale.pk, sale.version, variants[line.variant_id], line.quantity
        )
    order.sale = sale
    order.status = "ACCEPTED"
    order.handled_by = actor
    order.handled_at = timezone.now()
    if hold_pickup and not order.delivery_address and order.payment_preference != "VNPAY":
        order.pickup_expires_at = order.handled_at + timedelta(hours=48)
    order.version += 1
    order.save()
    audit(
        actor,
        "ACCEPT_WEB",
        order,
        {"sale": sale.code, "price_change_acknowledged": bool(price_ack)},
    )
    return order


@transaction.atomic
def cancel_order(pk, version, *, owner=None, account=None, actor=None, reason=""):
    if actor:
        actor = authorize(actor, [Role.ADMIN, Role.SALES], lock=True)
    order = WebOrder.objects.select_for_update().get(pk=pk)
    if not actor:
        if account is not None:
            allowed = (
                User.objects.filter(pk=account.pk, role=Role.CUSTOMER, is_active=True).exists()
                and order.account_id == account.pk
            )
        else:
            allowed = order.account_id is None and order.owner_hash == owner
        if not allowed:
            raise BusinessError("Không tìm thấy đơn hàng của bạn.")
    if order.status != "PENDING" or str(order.version) != str(version):
        raise BusinessError(
            "Chỉ hủy được yêu cầu còn chờ xác nhận. Vui lòng tải lại trạng thái mới nhất."
        )
    if actor and not reason.strip():
        raise BusinessError("Cần nhập lý do hủy để khách đối chiếu.")
    if actor and (len(reason.strip()) > 1000 or "\x00" in reason):
        raise BusinessError("Lý do hủy tối đa 1.000 ký tự và không chứa ký tự không hợp lệ.")
    order.status = "CANCELLED"
    order.reason = reason.strip() if actor else "Khách hủy trước khi cửa hàng tiếp nhận."
    order.cancel_origin = "STAFF" if actor else "CUSTOMER"
    order.handled_by = actor
    order.handled_at = timezone.now()
    order.version += 1
    order.save()
    if actor:
        audit(actor, "CANCEL_WEB", order, reason=order.reason)
    return order
