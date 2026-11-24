from datetime import datetime, time, timedelta
from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from store.forms.suppliers import SkuReplenishmentForm, SupplierDeliveryForm, SupplierOrderForm
from store.models import Role, SaleLine, Status, SupplierOrder
from store.services.documents import BusinessError
from store.services.pickup import held_quantities
from store.services.suppliers import (
    calculate_need,
    cancel_remaining,
    place_supplier_order,
    planned_incoming,
    receive_delivery,
    received_for,
)
from store.views.common import role_required, show_error


@role_required(Role.ADMIN, Role.WAREHOUSE)
def orders(request):
    qs = SupplierOrder.objects.select_related("supplier", "variant").order_by("-created_at", "-pk")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(
        request, "store/suppliers/list.html", {"title": "Đơn đặt nhà cung cấp", "page": page}
    )


@role_required(Role.ADMIN, Role.WAREHOUSE)
def new_order(request):
    form = SupplierOrderForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            order = place_supplier_order(request.user, form.cleaned_data)
            return redirect("supplier_order", pk=order.pk)
        except (BusinessError, ValidationError, IntegrityError) as exc:
            show_error(form, exc)
    return render(
        request,
        "store/shared/form.html",
        {
            "title": "Ghi đơn đã đặt nhà cung cấp",
            "form": form,
            "back": reverse("supplier_orders"),
            "hint": "Ghi số lượng nhà cung cấp đã xác nhận và ngày dự kiến giao cho từng mã cỡ, màu.",
        },
    )


@role_required(Role.ADMIN, Role.WAREHOUSE)
def detail(request, pk):
    order = get_object_or_404(SupplierOrder.objects.select_related("variant", "supplier"), pk=pk)
    form = SupplierDeliveryForm(
        request.POST if request.method == "POST" else None, initial={"request_key": uuid4()}
    )
    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data.copy()
            data.pop("checked")
            receipt = receive_delivery(request.user, pk, **data)
            messages.success(request, "Đã ghi sổ lượng hàng giao đạt kiểm tra.")
            return redirect("document", kind="receipt", pk=receipt.pk)
        except (BusinessError, ValidationError, IntegrityError) as exc:
            show_error(form, exc)
    return render(
        request,
        "store/suppliers/detail.html",
        {
            "title": order.reference,
            "order": order,
            "remaining": order.ordered_qty - received_for(order),
            "receipts": order.receipts.filter(status=Status.POSTED).order_by("-posted_at"),
            "form": form,
        },
    )


@require_POST
@role_required(Role.ADMIN, Role.WAREHOUSE)
def close_order(request, pk):
    get_object_or_404(SupplierOrder, pk=pk)
    try:
        cancel_remaining(request.user, pk)
        messages.success(request, "Đã đóng phần hàng còn chờ.")
    except BusinessError as exc:
        messages.error(request, str(exc))
    return redirect("supplier_order", pk=pk)


@role_required(Role.ADMIN, Role.WAREHOUSE)
def sku_plan(request):
    form = SkuReplenishmentForm(request.GET or None)
    result = None
    if form.is_valid():
        data = form.cleaned_data
        variant = data["variant"]
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today - timedelta(days=30), time.min))
        end = timezone.make_aware(datetime.combine(today, time.min))
        monthly = (
            SaleLine.objects.filter(
                variant=variant,
                sale__status=Status.POSTED,
                sale__posted_at__gte=start,
                sale__posted_at__lt=end,
            )
            .exclude(sale__corrections__status=Status.POSTED)
            .aggregate(total=Sum("quantity"))["total"]
            or 0
        )
        held = held_quantities([variant.pk]).get(variant.pk, 0)
        available = max(0, variant.balance.quantity - held)
        incoming = planned_incoming(variant, today, today + timedelta(days=data["lead_days"]))
        result = {
            "variant": variant,
            "monthly": monthly,
            "held": held,
            "available": available,
            "incoming": incoming,
            **calculate_need(monthly, data["lead_days"], data["safety"], available, incoming),
        }
    return render(
        request,
        "store/forecast/sku_plan.html",
        {"title": "Gợi ý nhập theo biến thể", "form": form, "result": result},
    )
