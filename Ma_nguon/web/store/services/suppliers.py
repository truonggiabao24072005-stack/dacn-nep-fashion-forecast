from decimal import ROUND_CEILING, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from store.models import GoodsReceipt, ReceiptLine, Role, Status, SupplierOrder
from store.services.documents import (
    BusinessError,
    _lock_stock,
    audit,
    authorize,
    confirm_document,
    create_document,
    set_line,
)


def received_for(order):
    return (
        ReceiptLine.objects.filter(
            receipt__supplier_order=order,
            receipt__status=Status.POSTED,
        )
        .exclude(receipt__corrections__status=Status.POSTED)
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )


@transaction.atomic
def place_supplier_order(actor, data):
    actor = authorize(actor, [Role.ADMIN, Role.WAREHOUSE], lock=True)
    _lock_stock([data["variant"].pk])
    order = SupplierOrder(created_by=actor, **data)
    order.full_clean()
    order.save()
    audit(actor, "PLACE_SUPPLIER_ORDER", order)
    return order


@transaction.atomic
def receive_delivery(actor, pk, *, quantity, unit_cost, delivery_reference, request_key):
    actor = authorize(actor, [Role.ADMIN, Role.WAREHOUSE], lock=True)
    order = SupplierOrder.objects.select_for_update().get(pk=pk)
    previous = GoodsReceipt.objects.filter(
        supplier_order=order, delivery_reference=delivery_reference
    ).first()
    if previous:
        line = previous.lines.get()
        if line.quantity == quantity and line.unit_cost == unit_cost:
            return previous
        raise BusinessError("Mã giao hàng đã được ghi sổ với số lượng hoặc giá khác.")
    if order.cancelled_at or not 0 < quantity <= order.ordered_qty - received_for(order):
        raise BusinessError("Số lượng đạt vượt phần còn chờ hoặc đơn đặt đã đóng.")
    receipt = create_document(
        actor,
        "receipt",
        {
            "supplier": order.supplier,
            "delivery_reference": delivery_reference,
            "note": f"Nhận hàng theo đơn đặt {order.reference}.",
        },
    )
    receipt.supplier_order = order
    receipt.save(update_fields=["supplier_order"])
    receipt = set_line(
        actor, "receipt", receipt.pk, receipt.version, order.variant, quantity, unit_cost
    )
    return confirm_document(actor, "receipt", receipt.pk, receipt.version, request_key)


@transaction.atomic
def cancel_remaining(actor, pk):
    actor = authorize(actor, [Role.ADMIN, Role.WAREHOUSE], lock=True)
    order = SupplierOrder.objects.select_for_update().get(pk=pk)
    if order.cancelled_at or received_for(order) >= order.ordered_qty:
        raise BusinessError("Đơn đặt đã đóng.")
    order.cancelled_at = timezone.now()
    order.save(update_fields=["cancelled_at", "updated_at"])
    audit(actor, "CANCEL_SUPPLIER_BALANCE", order)


def planned_incoming(variant, today, through):
    return sum(
        max(0, order.ordered_qty - received_for(order))
        for order in SupplierOrder.objects.filter(
            variant=variant, cancelled_at__isnull=True, expected_on__range=(today, through)
        )
    )


def calculate_need(monthly, lead_days, safety, available, incoming):
    lead_demand = Decimal(monthly) * lead_days / 30
    gross = max(
        0, int((lead_demand + safety - available).to_integral_value(rounding=ROUND_CEILING))
    )
    return {"lead_demand": lead_demand, "gross": gross, "quantity": max(0, gross - incoming)}
