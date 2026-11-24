from django.db import transaction
from django.db.models import F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from store.models import Role, Status, WebOrder, WebOrderLine


def active_holds():
    return WebOrderLine.objects.filter(
        order__status="ACCEPTED",
        order__sale__status=Status.DRAFT,
        order__pickup_expires_at__gt=timezone.now(),
    )


def with_available_stock(variants):
    held = active_holds().filter(variant_id=OuterRef("pk")).order_by().values("variant_id")
    quantity = Subquery(held.annotate(total=Sum("quantity")).values("total"))
    return variants.annotate(
        available_stock=Greatest(0, F("balance__quantity") - Coalesce(quantity, 0))
    )


def held_quantities(variant_ids, *, exclude_sale=None):
    rows = active_holds().filter(variant_id__in=variant_ids)
    if exclude_sale is not None:
        rows = rows.exclude(order__sale_id=exclude_sale)
    return dict(
        rows.values("variant_id").annotate(total=Sum("quantity")).values_list("variant_id", "total")
    )


@transaction.atomic
def close_missed_pickup(actor, order_id):
    from store.services.documents import BusinessError, authorize, cancel_draft

    actor = authorize(actor, [Role.ADMIN, Role.SALES], lock=True)
    order = WebOrder.objects.select_for_update().get(pk=order_id)
    if not order.pickup_expires_at or order.pickup_expires_at > timezone.now() or not order.sale_id:
        raise BusinessError("Chỉ đóng đơn nhận tại cửa hàng đã hết hạn giữ.")
    sale = order.sale
    return cancel_draft(
        actor, "sale", sale.pk, sale.version, "Khách không đến nhận trước hạn giữ hàng."
    )
