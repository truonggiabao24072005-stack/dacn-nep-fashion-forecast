from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from store.forecast.replenishment import sellable_variants
from store.forms.catalog import build_catalog_form
from store.models import Customer, Product
from store.services.catalog import CATALOGS, catalog_roles, save_catalog
from store.services.documents import BusinessError, authorize
from store.services.search import filter_queryset_text
from store.validation import positive_identifier
from store.views.common import show_error


@login_required
def catalog_list(request, kind):
    if kind not in CATALOGS:
        raise Http404
    authorize(request.user, catalog_roles(kind))
    model, title, fields = CATALOGS[kind]
    qs = model.objects.all()
    q = request.GET.get("q", "").strip()
    if kind == "variants":
        qs = qs.select_related("product", "size", "color", "balance")
        if q:
            qs = filter_queryset_text(
                qs,
                q,
                (
                    "sku",
                    "product__code",
                    "product__name",
                    "product__category__name",
                    "product__brand__name",
                    "size__code",
                    "size__name",
                    "color__code",
                    "color__name",
                ),
                size_paths=("size__code", "size__name"),
            )
    elif q:
        search_fields = ["code", "name"]
        if kind == "products":
            search_fields += ["category__name", "brand__name"]
        elif kind in ("customers", "suppliers"):
            search_fields.append("phone")
        qs = filter_queryset_text(qs, q, search_fields)
    active = request.GET.get("active", "1" if kind in ["products", "variants"] else "")
    if active in ["1", "0"]:
        if kind == "variants":
            eligible = sellable_variants()
            qs = qs.filter(pk__in=eligible) if active == "1" else qs.exclude(pk__in=eligible)
        else:
            qs = qs.filter(is_active=active == "1")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "store/catalog/list.html",
        {
            "title": title,
            "kind": kind,
            "page": page,
            "sellable_variant_ids": (
                set(
                    sellable_variants()
                    .filter(pk__in=[obj.pk for obj in page])
                    .values_list("pk", flat=True)
                )
                if kind == "variants"
                else set()
            ),
            "q": q,
            "active": active,
            "writable": request.user.role in catalog_roles(kind, True),
        },
    )


@login_required
def catalog_edit(request, kind, pk=None):
    if kind not in CATALOGS:
        raise Http404
    authorize(request.user, catalog_roles(kind, True))
    model, title, _ = CATALOGS[kind]
    obj = get_object_or_404(model, pk=pk) if pk else None
    form = build_catalog_form(
        kind, request.POST if request.method == "POST" else None, instance=obj
    )
    parent_product = None
    if not pk and kind == "products":
        form.initial.setdefault("unit", "đôi")
    if not pk and kind == "variants" and "product" in request.GET:
        product_id = positive_identifier(request.GET.get("product"))
        parent_product = get_object_or_404(Product, pk=product_id)
        form.initial.update(product=parent_product.pk, is_active=parent_product.is_active)
        form.fields["product"].disabled = True
    if request.method == "POST" and form.is_valid():
        try:
            saved = save_catalog(
                request.user, kind, form.cleaned_data, pk, form.cleaned_data["version"]
            )
            if (
                kind == "customers"
                and saved.phone
                and Customer.objects.filter(phone=saved.phone).exclude(pk=saved.pk).exists()
            ):
                messages.warning(
                    request,
                    "Có hồ sơ khác cùng số điện thoại. Đã giữ riêng hồ sơ, cần kiểm tra người thực tế.",
                )
            if kind == "products" and request.POST.get("next_step") == "variant":
                messages.success(request, "Đã lưu sản phẩm. Bây giờ bạn có thể thêm cỡ và màu.")
                return redirect(
                    reverse("catalog_new", args=["variants"], query={"product": saved.pk})
                )
            if kind == "variants" and request.POST.get("next_step") == "another_variant":
                messages.success(request, "Đã lưu biến thể. Tồn kho được cập nhật qua phiếu nhập.")
                return redirect(
                    reverse("catalog_new", args=["variants"], query={"product": saved.product_id})
                )
            messages.success(request, "Đã lưu hồ sơ.")
            return redirect("catalog", kind=kind)
        except (BusinessError, ValidationError, IntegrityError) as exc:
            show_error(form, exc)
    if kind in ("products", "variants"):
        return render(
            request,
            "store/catalog/product_form.html",
            {
                "title": f"{'Chỉnh sửa' if pk else 'Thêm'} {title.lower()}",
                "form": form,
                "kind": kind,
                "editing": bool(pk),
                "parent_product": parent_product,
                "back": reverse("catalog", args=["products" if parent_product else kind]),
            },
        )
    return render(
        request,
        "store/shared/form.html",
        {
            "title": ("Chỉnh sửa " if pk else "Tạo ") + title.lower(),
            "form": form,
            "back": reverse("catalog", args=[kind]),
            "hint": "Ngừng sử dụng để giữ lịch sử. Tồn kho chỉ thay đổi qua chứng từ.",
        },
    )
