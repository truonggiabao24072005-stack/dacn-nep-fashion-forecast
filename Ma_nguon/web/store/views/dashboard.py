from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.shortcuts import render
from django.utils import timezone

from store.forecast.replenishment import sellable_variants
from store.models import (
    STAFF_ROLES,
    GoodsReceipt,
    Product,
    Role,
    SaleOrder,
    Status,
    StockBalance,
    WebOrder,
)
from store.services.documents import authorize
from store.services.reports import sales_report


@login_required
def dashboard(request):
    u = authorize(request.user, STAFF_ROLES)
    today = timezone.localdate()
    balances = StockBalance.objects.select_related(
        "variant__product", "variant__size", "variant__color"
    )
    eligible = sellable_variants()
    low = balances.filter(
        variant__in=eligible,
        variant__low_stock_threshold__isnull=False,
        quantity__lte=F("variant__low_stock_threshold"),
    )
    result = {
        "title": "Tổng quan cửa hàng",
        "today": today,
        "product_count": Product.objects.filter(
            is_active=True, category__is_active=True, brand__is_active=True
        ).count(),
        "sku_count": eligible.count(),
        "low_count": low.count(),
        "low": low[:6],
        "stock": balances.filter(variant__in=eligible).aggregate(n=Sum("quantity"))["n"] or 0,
        "unavailable_stock": balances.exclude(variant__in=eligible).aggregate(n=Sum("quantity"))[
            "n"
        ]
        or 0,
        "out_of_stock_count": eligible.filter(balance__quantity=0).count(),
        "unconfigured_count": eligible.filter(low_stock_threshold__isnull=True).count(),
    }
    if u.role == Role.ADMIN:
        result["summary"] = sales_report(u, today.replace(day=1), today)
    sales = (
        SaleOrder.objects.all() if u.role == Role.ADMIN else SaleOrder.objects.filter(created_by=u)
    )
    receipts = (
        GoodsReceipt.objects.all()
        if u.role == Role.ADMIN
        else GoodsReceipt.objects.filter(created_by=u)
    )
    result["sale_drafts"] = (
        sales.filter(status=Status.DRAFT).count() if u.role in [Role.ADMIN, Role.SALES] else None
    )
    result["receipt_drafts"] = (
        receipts.filter(status=Status.DRAFT).count()
        if u.role in [Role.ADMIN, Role.WAREHOUSE]
        else None
    )
    result["pending_web"] = (
        WebOrder.objects.filter(status="PENDING").count()
        if u.role in [Role.ADMIN, Role.SALES]
        else None
    )
    result["recent_kind"] = "receipt" if u.role == Role.WAREHOUSE else "sale"
    result["recent"] = (receipts if u.role == Role.WAREHOUSE else sales).exclude(
        status=Status.CANCELLED
    )[:5]
    return render(request, "store/dashboard.html", result)
