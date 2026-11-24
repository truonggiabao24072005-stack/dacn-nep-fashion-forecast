"""Ghi chứng từ, khoản thu và biến động kho trong cùng giao dịch."""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from store.models import (
    STAFF_ROLES,
    AdjustmentLine,
    AuditEvent,
    Brand,
    Category,
    Color,
    Customer,
    DocumentCorrection,
    GoodsReceipt,
    OperationRequest,
    Product,
    Role,
    SaleOrder,
    SalePayment,
    Size,
    Status,
    StockAdjustment,
    StockBalance,
    StockEntry,
    StockPosting,
    Supplier,
    User,
    Variant,
)


class BusinessError(Exception):
    pass


DOCUMENTS = {
    "sale": SaleOrder,
    "receipt": GoodsReceipt,
    "adjustment": StockAdjustment,
    "correction": DocumentCorrection,
}
PREFIXES = {"sale": "BH", "receipt": "PN", "adjustment": "KK", "correction": "BS"}


def code(prefix):
    return f"{prefix}-{uuid4().hex[:14].upper()}"


def quantity(value, *, zero=False):
    text = str(value)
    if not text.isascii() or not text.isdigit():
        raise BusinessError(
            "Số lượng phải là số nguyên không âm." if zero else "Số lượng phải là số nguyên dương."
        )
    canonical = text.lstrip("0") or "0"
    if len(canonical) > 10:
        raise BusinessError("Số lượng nằm ngoài giới hạn cho phép.")
    n = int(canonical)
    if n < (0 if zero else 1) or n > 2_147_483_647:
        raise BusinessError("Số lượng nằm ngoài giới hạn cho phép.")
    return n


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BusinessError("Số tiền không hợp lệ.")
    if (
        not result.is_finite()
        or result < 0
        or result != result.to_integral_value()
        or result >= 10**18
    ):
        raise BusinessError("Số tiền phải là đồng Việt Nam nguyên, không âm và nhỏ hơn 10^18.")
    return result.quantize(Decimal("1"))


def authorize(actor, roles, *, lock=False):
    query = User.objects.select_for_update() if lock else User.objects
    try:
        fresh = query.get(pk=actor.pk, is_active=True)
    except User.DoesNotExist:
        raise PermissionDenied("Tài khoản đã ngừng hoạt động.")
    if fresh.role not in STAFF_ROLES or fresh.role not in roles:
        raise PermissionDenied("Bạn không có quyền thực hiện chức năng này.")
    return fresh


def roles_for(kind):
    if kind == "sale":
        return [Role.ADMIN, Role.SALES]
    if kind == "receipt":
        return [Role.ADMIN, Role.WAREHOUSE]
    return [Role.ADMIN]


def audit(actor, action, obj, changed=None, reason=""):
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=type(obj).__name__,
        object_id=str(obj.pk),
        changed_fields=changed or {},
        reason=reason,
    )


def owned_document(actor, kind, pk, *, lock=False):
    actor = authorize(actor, roles_for(kind))
    query = DOCUMENTS[kind].objects.select_for_update() if lock else DOCUMENTS[kind].objects
    doc = query.get(pk=pk)
    if actor.role != Role.ADMIN and doc.created_by_id != actor.pk:
        raise PermissionDenied("Chứng từ này thuộc nhân viên khác.")
    return doc


def draft_version(doc, version):
    if doc.status != Status.DRAFT:
        raise BusinessError(
            "Chỉ được sửa hoặc xác nhận chứng từ nháp. Chứng từ đã ghi sổ được giữ nguyên."
        )
    if str(doc.version) != str(version):
        raise BusinessError("Chứng từ đã thay đổi. Hãy tải lại và đối chiếu trước khi tiếp tục.")


def _snapshot(line, variant):
    line.sku_snapshot = variant.sku
    line.name_snapshot = variant.product.name
    line.variant_snapshot = f"{variant.size.name} / {variant.color.name} · {variant.product.unit}"


def _lock_stock(ids, *, active=True):
    ids = sorted(set(ids))
    product_ids = set(Variant.objects.filter(pk__in=ids).values_list("product_id", flat=True))
    products = {
        p.pk: p
        for p in Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk")
    }
    variants = list(Variant.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if len(variants) != len(ids):
        raise BusinessError("Có biến thể không tồn tại.")
    if any(v.product_id not in products for v in variants):
        raise BusinessError("Biến thể đã thay đổi sản phẩm. Hãy tải lại chứng từ.")
    masters = {}
    for model, fk in [(Category, "category_id"), (Brand, "brand_id")]:
        masters[model] = {
            o.pk: o
            for o in model.objects.select_for_update()
            .filter(pk__in={getattr(p, fk) for p in products.values()})
            .order_by("pk")
        }
    for model, fk in [(Size, "size_id"), (Color, "color_id")]:
        masters[model] = {
            o.pk: o
            for o in model.objects.select_for_update()
            .filter(pk__in={getattr(v, fk) for v in variants})
            .order_by("pk")
        }
    for v in variants:
        v.product = products[v.product_id]
        v.size = masters[Size][v.size_id]
        v.color = masters[Color][v.color_id]
        p = v.product
        if active and not all(
            [
                v.is_active,
                p.is_active,
                masters[Category][p.category_id].is_active,
                masters[Brand][p.brand_id].is_active,
                v.size.is_active,
                v.color.is_active,
            ]
        ):
            raise BusinessError(f"{v.sku}: hàng hóa hoặc thuộc tính đã ngừng sử dụng.")
    balances = {
        b.variant_id: b
        for b in StockBalance.objects.select_for_update()
        .filter(variant_id__in=ids)
        .order_by("variant_id")
    }
    if len(balances) != len(ids):
        raise BusinessError("Thiếu số dư kho. Cần quản trị kiểm tra dữ liệu.")
    return {v.pk: v for v in variants}, balances


def _post_stock(actor, doc, kind, deltas, balances):
    for vid, delta in deltas.items():
        if balances[vid].quantity + delta < 0:
            raise BusinessError(
                f"{balances[vid].variant.sku}: không đủ tồn; hiện có {balances[vid].quantity}."
            )
        if balances[vid].quantity + delta > 2_147_483_647:
            raise BusinessError("Số tồn vượt giới hạn dữ liệu.")
    posting = StockPosting.objects.create(
        kind=kind,
        business_key=f"{type(doc).__name__}:{doc.pk}",
        posted_by=actor,
        posted_at=timezone.now(),
    )
    for vid in sorted(deltas):
        delta = deltas[vid]
        if delta:
            b = balances[vid]
            b.quantity += delta
            b.version += 1
            b.save(update_fields=["quantity", "version", "updated_at"])
            StockEntry.objects.create(posting=posting, variant_id=vid, delta=delta)
    doc.status = Status.POSTED
    doc.posted_at = posting.posted_at
    doc.posted_by = actor
    doc.stock_posting = posting
    doc.version += 1
    doc.save()
    audit(actor, "POST", doc, {str(k): v for k, v in deltas.items()})
    return doc


def _command(actor, operation, key, payload, roles, callback):
    try:
        request_key = UUID(str(key))
    except (TypeError, ValueError, AttributeError):
        raise BusinessError("Mã yêu cầu không hợp lệ. Hãy tải lại trang.")
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    with transaction.atomic():
        actor = authorize(actor, roles, lock=True)
        previous = OperationRequest.objects.filter(
            actor=actor, operation=operation, request_key=request_key
        ).first()
        if previous:
            if previous.payload_hash != fingerprint:
                raise BusinessError(
                    "Mã yêu cầu đã dùng với nội dung khác. Không được gửi lại bằng mã cũ."
                )
            return DOCUMENTS[previous.result_type].objects.get(pk=previous.result_id)
        result, kind = callback(actor)
        OperationRequest.objects.create(
            actor=actor,
            operation=operation,
            request_key=request_key,
            payload_hash=fingerprint,
            result_type=kind,
            result_id=result.pk,
        )
        return result


@transaction.atomic
def create_document(actor, kind, values):
    actor = authorize(actor, roles_for(kind), lock=True)
    if kind == "receipt":
        supplier = Supplier.objects.select_for_update().get(pk=values["supplier"].pk)
        if not supplier.is_active:
            raise BusinessError("Nhà cung cấp đã ngừng sử dụng.")
        doc = GoodsReceipt(
            supplier=supplier,
            delivery_reference=values.get("delivery_reference", ""),
            note=values.get("note", ""),
        )
    elif kind == "sale":
        customer = values.get("customer")
        if customer and not Customer.objects.get(pk=customer.pk).is_active:
            raise BusinessError("Khách hàng đã ngừng sử dụng.")
        doc = SaleOrder(customer=customer)
    elif kind == "adjustment":
        if values.get("kind") not in ["OPENING", "COUNT"] or not values.get("reason", "").strip():
            raise BusinessError("Cần chọn loại kiểm đếm và nhập lý do.")
        doc = StockAdjustment(
            kind=values["kind"],
            reason=values["reason"],
            source_reference=values.get("source_reference", ""),
        )
    else:
        raise BusinessError("Loại chứng từ không hợp lệ.")
    doc.code = code(PREFIXES[kind])
    doc.created_by = actor
    doc.save()
    audit(actor, "CREATE_DRAFT", doc)
    return doc


@transaction.atomic
def set_line(actor, kind, pk, version, variant, amount, unit_cost=None, *, remove=False):
    actor = authorize(actor, roles_for(kind), lock=True)
    doc = owned_document(actor, kind, pk, lock=True)
    draft_version(doc, version)
    if kind not in ["sale", "receipt", "adjustment"]:
        raise BusinessError("Chứng từ này không nhận dòng tùy ý.")
    if remove:
        doc.lines.filter(variant=variant).delete()
    else:
        variants, balances = _lock_stock([variant.pk], active=kind != "adjustment")
        v = variants[variant.pk]
        if kind == "adjustment":
            b = balances[v.pk]
            doc.lines.update_or_create(
                variant=v,
                defaults={
                    "counted_qty": quantity(amount, zero=True),
                    "expected_qty": b.quantity,
                    "expected_version": b.version,
                },
            )
        elif kind == "sale":
            if v.selling_price <= 0:
                raise BusinessError("Hàng chưa được cấu hình giá bán lớn hơn 0.")
            doc.lines.update_or_create(
                variant=v, defaults={"quantity": quantity(amount), "unit_price": v.selling_price}
            )
        else:
            doc.lines.update_or_create(
                variant=v, defaults={"quantity": quantity(amount), "unit_cost": money(unit_cost)}
            )
    if kind in ["sale", "receipt"]:
        doc.total_amount = money(sum((line.line_total for line in doc.lines.all()), Decimal("0")))
    doc.version += 1
    doc.save()
    audit(actor, "EDIT_DRAFT", doc, {"version": doc.version})
    return doc


@transaction.atomic
def refresh_prices(actor, pk, version):
    actor = authorize(actor, roles_for("sale"), lock=True)
    doc = owned_document(actor, "sale", pk, lock=True)
    draft_version(doc, version)
    variants, _ = _lock_stock(doc.lines.values_list("variant_id", flat=True))
    for line in doc.lines.all():
        price = variants[line.variant_id].selling_price
        if price <= 0:
            raise BusinessError("Có hàng chưa cấu hình giá bán hợp lệ.")
        line.unit_price = price
        line.save(update_fields=["unit_price"])
    doc.total_amount = money(sum((line.line_total for line in doc.lines.all()), Decimal("0")))
    doc.version += 1
    doc.save()
    audit(actor, "REFRESH_PRICES", doc)
    return doc


@transaction.atomic
def update_header(actor, kind, pk, version, values):
    actor = authorize(actor, roles_for(kind), lock=True)
    doc = owned_document(actor, kind, pk, lock=True)
    draft_version(doc, version)
    if kind == "sale":
        customer = values.get("customer")
        if customer and not Customer.objects.select_for_update().get(pk=customer.pk).is_active:
            raise BusinessError("Khách hàng đã ngừng sử dụng.")
        doc.customer = customer
    elif kind == "receipt":
        supplier = Supplier.objects.select_for_update().get(pk=values["supplier"].pk)
        if not supplier.is_active:
            raise BusinessError("Nhà cung cấp đã ngừng sử dụng.")
        doc.supplier = supplier
        doc.delivery_reference = values.get("delivery_reference", "")
        doc.note = values.get("note", "")
    else:
        raise BusinessError("Loại chứng từ này không cho sửa thông tin đầu phiếu.")
    doc.version += 1
    doc.save()
    audit(actor, "UPDATE_DRAFT_HEADER", doc, {"version": doc.version})
    return doc


def confirm_document(actor, kind, pk, version, request_key, payment=None):
    payment = payment or {}
    payload = {"kind": kind, "id": pk, "version": str(version), "payment": payment}

    def perform(fresh):
        doc = owned_document(fresh, kind, pk, lock=True)
        draft_version(doc, version)
        lines = list(doc.lines.order_by("variant_id"))
        if not lines:
            raise BusinessError("Chứng từ cần ít nhất một dòng hàng.")
        variants, balances = _lock_stock(
            [line.variant_id for line in lines], active=kind != "adjustment"
        )
        if kind == "adjustment":
            deltas = {}
            for line in lines:
                b = balances[line.variant_id]
                if b.version != line.expected_version or b.quantity != line.expected_qty:
                    raise BusinessError(
                        f"{variants[line.variant_id].sku}: tồn đã thay đổi sau khi kiểm đếm. Cần đối chiếu lại dòng."
                    )
                if doc.kind == "OPENING" and (
                    StockEntry.objects.filter(variant_id=line.variant_id).exists()
                    or AdjustmentLine.objects.filter(
                        variant_id=line.variant_id,
                        adjustment__kind="OPENING",
                        adjustment__status=Status.POSTED,
                    ).exists()
                ):
                    raise BusinessError(
                        "SKU đã có vận hành hoặc đã mở tồn đầu kỳ. Hãy sử dụng kiểm đếm có căn cứ."
                    )
                deltas[line.variant_id] = line.counted_qty - b.quantity
            return (
                _post_stock(
                    fresh,
                    doc,
                    "OPENING" if doc.kind == "OPENING" else "ADJUSTMENT",
                    deltas,
                    balances,
                ),
                kind,
            )
        if kind == "sale":
            from store.services.pickup import held_quantities

            linked = getattr(doc, "web_order", None)
            if linked and linked.pickup_expires_at and linked.pickup_expires_at <= timezone.now():
                raise BusinessError("Đơn nhận tại cửa hàng đã hết hạn giữ.")
            if (
                linked
                and linked.pickup_expires_at
                and {line.variant_id: line.quantity for line in lines}
                != dict(linked.lines.values_list("variant_id", "quantity"))
            ):
                raise BusinessError("Đơn bán khác các dòng khách đã giữ. Hãy kiểm tra lại.")
            held = held_quantities(balances, exclude_sale=doc.pk)
            for line in lines:
                if (
                    balances[line.variant_id].quantity - held.get(line.variant_id, 0)
                    < line.quantity
                ):
                    raise BusinessError(
                        f"{line.variant.sku}: không đủ tồn sau khi trừ hàng đang giữ."
                    )
        doc.total_amount = money(sum((line.line_total for line in lines), Decimal("0")))
        for line in lines:
            v = variants[line.variant_id]
            if kind == "sale" and (v.selling_price <= 0 or v.selling_price != line.unit_price):
                raise BusinessError(
                    f"{v.sku}: giá bán đã thay đổi. Chọn cập nhật giá nháp, xem lại rồi xác nhận."
                )
            if (
                kind == "receipt"
                and line.unit_cost == 0
                and (fresh.role != Role.ADMIN or not doc.note.strip())
            ):
                raise BusinessError(
                    "Giá nhập 0 cần quản trị xác nhận và có ghi chú căn cứ trên phiếu."
                )
            _snapshot(line, v)
            line.save(update_fields=["sku_snapshot", "name_snapshot", "variant_snapshot"])
        if kind == "sale":
            if doc.customer_id:
                customer = Customer.objects.select_for_update().get(pk=doc.customer_id)
                if not customer.is_active:
                    raise BusinessError("Hồ sơ khách hàng đã ngừng sử dụng. Cần đối chiếu lại đơn.")
                doc.customer_name_snapshot = customer.name
            else:
                doc.customer_name_snapshot = "Khách lẻ"
            method = payment.get("method")
            from store.models import GatewayPayment

            web_order = getattr(doc, "web_order", None)
            if web_order and web_order.payment_preference == "VNPAY":
                verified = GatewayPayment.objects.filter(
                    order=web_order,
                    status="REVIEW",
                    amount=doc.total_amount,
                    provider_reference=payment.get("reference"),
                ).exists()
                same_lines = {line.variant_id: line.quantity for line in lines} == dict(
                    web_order.lines.values_list("variant_id", "quantity")
                )
                if method != "VNPAY" or not verified or not same_lines:
                    raise BusinessError(
                        "Đơn VNPAY chỉ được ghi sổ sau khi cổng thanh toán xác nhận."
                    )
            elif method not in ["CASH", "TRANSFER"]:
                raise BusinessError("Cần chọn phương thức thanh toán được ghi nhận.")
            received = change = None
            if method == "CASH":
                received = money(payment.get("cash_received", ""))
                if received < doc.total_amount:
                    raise BusinessError("Tiền khách đưa chưa đủ tổng đơn.")
                change = received - doc.total_amount
            elif method == "TRANSFER" and not payment.get("transfer_ack"):
                raise BusinessError(
                    "Nhân viên cần xác nhận đã đối chiếu khoản chuyển với tổng đơn."
                )
            SalePayment.objects.create(
                sale=doc,
                method=method,
                amount=doc.total_amount,
                cash_received=received,
                change_amount=change,
                reference=str(payment.get("reference", ""))[:100],
                recorded_by=fresh,
            )
            deltas = {line.variant_id: -line.quantity for line in lines}
            return _post_stock(fresh, doc, "SALE", deltas, balances), kind
        supplier = Supplier.objects.select_for_update().get(pk=doc.supplier_id)
        if not supplier.is_active:
            raise BusinessError("Nhà cung cấp đã ngừng hoạt động.")
        doc.supplier_name_snapshot = supplier.name
        return (
            _post_stock(
                fresh, doc, "RECEIPT", {line.variant_id: line.quantity for line in lines}, balances
            ),
            kind,
        )

    return _command(actor, f"post_{kind}", request_key, payload, roles_for(kind), perform)


@transaction.atomic
def cancel_draft(actor, kind, pk, version, reason):
    actor = authorize(actor, roles_for(kind), lock=True)
    doc = owned_document(actor, kind, pk, lock=True)
    draft_version(doc, version)
    if not str(reason).strip():
        raise BusinessError("Cần nhập lý do hủy nháp.")
    doc.status = Status.CANCELLED
    doc.cancel_reason = str(reason).strip()
    doc.version += 1
    doc.save()
    audit(actor, "CANCEL_DRAFT", doc, reason=doc.cancel_reason)
    return doc


def correct_document(
    actor,
    original_kind,
    pk,
    request_key,
    *,
    reason,
    evidence,
    goods_ack=False,
    financial_ack=False,
):
    if original_kind not in ["sale", "receipt"]:
        raise BusinessError("Chỉ hỗ trợ sửa sai toàn bộ phiếu nhập hoặc đơn bán đã xác nhận.")
    payload = {
        "kind": original_kind,
        "id": pk,
        "reason": reason,
        "evidence": evidence,
        "goods_ack": bool(goods_ack),
        "financial_ack": bool(financial_ack),
    }

    def perform(fresh):
        original = owned_document(fresh, original_kind, pk, lock=True)
        if original.status != Status.POSTED:
            raise BusinessError("Chứng từ gốc chưa ghi sổ.")
        if original.corrections.filter(status=Status.POSTED).exists():
            raise BusinessError("Chứng từ đã được sửa sai toàn bộ; không được đảo lần hai.")
        if not str(reason).strip() or not str(evidence).strip():
            raise BusinessError("Cần lý do và căn cứ đối soát sửa sai.")
        if original_kind == "sale" and not (goods_ack and financial_ack):
            raise BusinessError("Cần xác nhận đã thu hồi đủ hàng còn bán được và đã đối soát tiền.")
        lines = list(original.lines.all())
        _, balances = _lock_stock([line.variant_id for line in lines], active=False)
        kwargs = (
            {"original_sale": original}
            if original_kind == "sale"
            else {"original_receipt": original}
        )
        doc = DocumentCorrection.objects.create(
            code=code("BS"),
            created_by=fresh,
            reason=reason,
            evidence=evidence,
            goods_recovered_ack=goods_ack,
            financial_ack=financial_ack,
            amount_snapshot=original.total_amount if original_kind == "sale" else 0,
            **kwargs,
        )
        sign = 1 if original_kind == "sale" else -1
        result = _post_stock(
            fresh,
            doc,
            "CORRECTION",
            {line.variant_id: sign * line.quantity for line in lines},
            balances,
        )
        audit(fresh, "CORRECT_ORIGINAL", original, {"correction": doc.code}, reason=reason)
        return result, "correction"

    return _command(actor, "correct_document", request_key, payload, [Role.ADMIN], perform)
