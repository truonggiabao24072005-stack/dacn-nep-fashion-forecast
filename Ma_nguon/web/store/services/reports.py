from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from store.models import Role, SaleLine, Status, StockBalance
from store.services.documents import BusinessError, authorize


def period_bounds(start, end):
    if start > end:
        raise BusinessError("Ngày bắt đầu không được sau ngày kết thúc.")
    try:
        next_day = end + timedelta(days=1)
    except OverflowError:
        raise BusinessError(
            "Ngày kết thúc nằm ngoài phạm vi có thể lập báo cáo. Vui lòng chọn ngày khác."
        ) from None
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start, time.min), tz),
        timezone.make_aware(datetime.combine(next_day, time.min), tz),
    )


def sales_report(actor, start, end, group="day"):
    authorize(actor, [Role.ADMIN])
    a, b = period_bounds(start, end)
    fields = [
        "kind",
        "doc_id",
        "doc_code",
        "source_code",
        "event_at",
        "product_id",
        "product_name",
        "units",
        "value",
    ]
    amount = ExpressionWrapper(
        F("quantity") * F("unit_price"), output_field=DecimalField(max_digits=28, decimal_places=0)
    )
    base = (
        SaleLine.objects.filter(
            sale__status=Status.POSTED, sale__posted_at__gte=a, sale__posted_at__lt=b
        )
        .annotate(
            kind=Value("SALE"),
            doc_id=F("sale_id"),
            doc_code=F("sale__code"),
            source_code=F("sale__code"),
            event_at=F("sale__posted_at"),
            product_id=F("variant__product_id"),
            product_name=F("name_snapshot"),
            units=F("quantity"),
            value=amount,
        )
        .values(*fields)
    )
    corrections = (
        SaleLine.objects.filter(
            sale__corrections__status=Status.POSTED,
            sale__corrections__posted_at__gte=a,
            sale__corrections__posted_at__lt=b,
        )
        .annotate(
            kind=Value("CORRECTION"),
            doc_id=F("sale__corrections__pk"),
            doc_code=F("sale__corrections__code"),
            source_code=F("sale__code"),
            event_at=F("sale__corrections__posted_at"),
            product_id=F("variant__product_id"),
            product_name=F("name_snapshot"),
            units=F("quantity"),
            value=amount,
        )
        .values(*fields)
    )
    # A single UNION query reads one PostgreSQL statement snapshot. No repeated
    # order totals and no cross-query race between gross and correction amounts.
    records = list(base.union(corrections, all=True))
    periods = defaultdict(
        lambda: {"gross": Decimal(0), "correction": Decimal(0), "quantity": 0, "orders": set()}
    )
    products = defaultdict(
        lambda: {"gross_quantity": 0, "correction_quantity": 0, "value": Decimal(0), "name": ""}
    )
    docs = {}
    gross = reduced = Decimal(0)
    order_ids = set()
    correction_ids = set()
    quantity = 0
    for r in records:
        date = timezone.localtime(r["event_at"]).date()
        bucket = date.strftime("%Y-%m" if group == "month" else "%Y-%m-%d")
        p = periods[bucket]
        product = products[r["product_id"]]
        product["name"] = r["product_name"]
        if r["kind"] == "SALE":
            gross += r["value"]
            quantity += r["units"]
            order_ids.add(r["doc_id"])
            p["gross"] += r["value"]
            p["quantity"] += r["units"]
            p["orders"].add(r["doc_id"])
            product["gross_quantity"] += r["units"]
            product["value"] += r["value"]
        else:
            reduced += r["value"]
            quantity -= r["units"]
            correction_ids.add(r["doc_id"])
            p["correction"] += r["value"]
            p["quantity"] -= r["units"]
            product["correction_quantity"] += r["units"]
            product["value"] -= r["value"]
        key = (r["kind"], r["doc_id"])
        if key not in docs:
            docs[key] = {
                "kind": r["kind"],
                "id": r["doc_id"],
                "code": r["doc_code"],
                "source_code": r["source_code"],
                "at": r["event_at"],
                "value": Decimal(0),
                "units": 0,
            }
        docs[key]["value"] += r["value"]
        docs[key]["units"] += r["units"]
    timeline = [
        dict(
            period=k,
            gross=v["gross"],
            correction=v["correction"],
            net=v["gross"] - v["correction"],
            quantity=v["quantity"],
            orders=len(v["orders"]),
        )
        for k, v in sorted(periods.items())
    ]
    ranking = [
        dict(product_id=k, quantity=v["gross_quantity"] - v["correction_quantity"], **v)
        for k, v in products.items()
    ]
    ranking.sort(key=lambda row: (-row["quantity"], -row["value"], row["product_id"]))
    return {
        "gross": gross,
        "correction": reduced,
        "net": gross - reduced,
        "orders": len(order_ids),
        "correction_count": len(correction_ids),
        "quantity": quantity,
        "timeline": timeline,
        "ranking": ranking,
        "documents": sorted(docs.values(), key=lambda r: r["at"], reverse=True),
        "chart": {
            "labels": [r["period"] for r in timeline],
            "values": [float(r["net"]) for r in timeline],
        },
    }


def reconciliation(actor):
    authorize(actor, [Role.ADMIN])
    return (
        StockBalance.objects.select_related("variant")
        .annotate(ledger=Coalesce(Sum("variant__stock_entries__delta"), Value(0)))
        .exclude(quantity=F("ledger"))
    )
