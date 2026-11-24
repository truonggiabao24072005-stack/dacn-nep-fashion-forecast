from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from store.forecast.replenishment import sellable_variants
from store.models import STAFF_ROLES, Product, Role, StockBalance, StockEntry, Variant
from store.services.catalog import set_safety_stock
from store.services.documents import DOCUMENTS, BusinessError, authorize
from store.services.search import filter_queryset_text
from store.views.common import role_required, show_error


@login_required
def inventory(request):
    authorize(request.user, STAFF_ROLES)
    q = request.GET.get("q", "").strip()
    qs = StockBalance.objects.select_related(
        "variant__product", "variant__size", "variant__color"
    ).order_by("variant__sku")
    if q:
        qs = filter_queryset_text(
            qs,
            q,
            (
                "variant__sku",
                "variant__product__code",
                "variant__product__name",
                "variant__size__code",
                "variant__size__name",
                "variant__color__code",
                "variant__color__name",
            ),
            size_paths=("variant__size__code", "variant__size__name"),
        )
    mode = request.GET.get("mode", "active")
    eligible = sellable_variants()
    if mode == "active":
        qs = qs.filter(variant__in=eligible)
    elif mode == "unavailable":
        qs = qs.exclude(variant__in=eligible)
    elif mode == "out":
        qs = qs.filter(variant__in=eligible, quantity=0)
    if mode == "low":
        qs = qs.filter(
            variant__in=eligible,
            variant__low_stock_threshold__isnull=False,
            quantity__lte=F("variant__low_stock_threshold"),
        )
    if mode == "unconfigured":
        qs = qs.filter(variant__in=eligible, variant__low_stock_threshold__isnull=True)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "store/inventory/list.html",
        {
            "title": "Tồn kho theo biến thể",
            "page": page,
            "q": q,
            "mode": mode,
            "as_of": timezone.now(),
            "sellable_variant_ids": set(
                eligible.filter(pk__in=[b.variant_id for b in page]).values_list("pk", flat=True)
            ),
        },
    )


@role_required(Role.ADMIN, Role.WAREHOUSE)
def ledger(request, pk):
    variant = get_object_or_404(
        Variant.objects.select_related("product", "size", "color", "balance"), pk=pk
    )
    entries = (
        StockEntry.objects.filter(variant=variant)
        .select_related("posting__posted_by")
        .order_by("-posting_id")
    )
    page = Paginator(entries, 30).get_page(request.GET.get("page"))
    links = {}
    ids = [e.posting_id for e in page]
    for kind, model in DOCUMENTS.items():
        for obj in model.objects.filter(stock_posting_id__in=ids):
            links[obj.stock_posting_id] = (kind, obj)
    rows = []
    for entry in page:
        link = links.get(entry.posting_id)
        can_link = link and (
            request.user.role == Role.ADMIN
            or (link[0] == "receipt" and link[1].created_by_id == request.user.pk)
        )
        rows.append(
            {
                "entry": entry,
                "code": link[1].code if link else entry.posting.business_key,
                "url": reverse("document", args=[link[0], link[1].pk]) if can_link else "",
            }
        )
    return render(
        request,
        "store/inventory/ledger.html",
        {"title": "Sổ biến động " + variant.sku, "variant": variant, "rows": rows, "page": page},
    )


@role_required(Role.ADMIN)
def safety(request, pk):
    product = get_object_or_404(Product, pk=pk)

    class SafetyForm(forms.Form):
        quantity = forms.IntegerField(
            label=f"Tồn an toàn ({product.unit})", min_value=0, max_value=2_147_483_647
        )
        policy_id = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    policy = product.policies.filter(effective_to__isnull=True).first()
    form = SafetyForm(
        request.POST if request.method == "POST" else None,
        initial={
            "quantity": policy.safety_stock_qty if policy else None,
            "policy_id": policy.pk if policy else 0,
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            set_safety_stock(
                request.user,
                pk,
                form.cleaned_data["quantity"],
                expected_policy_id=form.cleaned_data["policy_id"],
            )
            messages.success(request, "Đã lưu chính sách tồn an toàn. Kết quả cũ cần tính lại.")
            return redirect("catalog", kind="products")
        except BusinessError as exc:
            show_error(form, exc)
    return render(
        request,
        "store/shared/form.html",
        {
            "title": "Tồn an toàn của " + product.name,
            "form": form,
            "back": reverse("catalog", args=["products"]),
            "hint": "Tham số ở cấp sản phẩm, khác ngưỡng cảnh báo của từng biến thể.",
        },
    )
