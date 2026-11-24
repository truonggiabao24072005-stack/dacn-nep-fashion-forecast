from django.core.paginator import Paginator
from django.db.models import Case, Exists, IntegerField, OuterRef, Prefetch, Subquery, When
from django.shortcuts import get_object_or_404

from store.models import Category, Color, Product, Size
from store.services.orders import active_variants
from store.services.search import filter_shop_variants
from store.services.presentation import (
    COLLECTION_CODES,
    COLOR_HEX,
    PHOTO_CREDITS,
    SOURCE_PRODUCTS,
    presentation,
)
from store.views.common import shop_render


def product_query(variants=None):
    variants = active_variants() if variants is None else variants
    return (
        Product.objects.select_related("category", "brand")
        .filter(is_active=True, category__is_active=True, brand__is_active=True)
        .prefetch_related(Prefetch("variants", queryset=variants, to_attr="shop_variants"))
    )


def card(product):
    variants = product.shop_variants
    colors = {
        v.color_id: {"name": v.color.name, "hex": COLOR_HEX.get(v.color.code, "#a8a79e")}
        for v in variants
    }
    available = [v for v in variants if v.available_stock > 0]
    prices = {v.selling_price for v in available or variants}
    return {
        "product": product,
        **presentation(product),
        "price": min(prices, default=None),
        "price_varies": len(prices) > 1,
        "has_stock": bool(available),
        "available_sizes": len({v.size_id for v in available}),
        "colors": list(colors.values()),
    }


def home(request):
    picks = ["MH03577", "MH02391", "MH13558", "MH24299", "MH01688", "MH18159", "MH03016", "MH07525"]
    priority = Case(
        *[When(code=code, then=rank) for rank, code in enumerate(picks)],
        default=len(picks),
        output_field=IntegerField(),
    )
    in_stock = active_variants().filter(available_stock__gt=0)
    products = list(
        product_query()
        .filter(variants__in=in_stock)
        .annotate(shop_priority=priority)
        .distinct()
        .order_by("shop_priority", "code")[:8]
    )
    collection = list(
        product_query()
        .filter(code__in=COLLECTION_CODES, variants__in=active_variants())
        .distinct()
        .order_by("-created_at", "code")[:4]
    )
    featured_cards = [card(product) for product in products]
    collection_cards = [card(product) for product in collection]
    pictured = [item for item in featured_cards + collection_cards if item["image"]]
    hero = next(iter(pictured), None)
    category_cards = {}
    for item in pictured[1:] + pictured[:1]:
        category_cards.setdefault(item["product"].category.code, item)
    story_photo = next((item for item in pictured if item["product"].code == "MH24299"), None)
    return shop_render(
        request,
        "home",
        {
            "title": "Giày, dép và xăng đan",
            "hero": hero,
            "category_cards": [
                category_cards[code] for code in ("GIA", "DEP", "SAN") if code in category_cards
            ],
            "story_photo": story_photo,
            "featured": featured_cards,
            "collection": collection_cards,
        },
    )


def photo_sources(request):
    codes = set(product_query().values_list("code", flat=True))
    assets = {SOURCE_PRODUCTS[code]["asset"] for code in codes.intersection(SOURCE_PRODUCTS)}
    photos = [
        row for row in PHOTO_CREDITS if row["asset"] in assets or row.get("gallery_for") in assets
    ]
    return shop_render(request, "photos", {"title": "Nguồn ảnh", "photos": photos})


def size_order(size):
    code = size.code.upper()
    if code.isascii() and code.isdigit():
        return (0, int(code))
    ranks = {
        "XXS": 0,
        "XS": 1,
        "S": 2,
        "M": 3,
        "L": 4,
        "XL": 5,
        "2XL": 6,
        "XXL": 6,
        "3XL": 7,
        "XXXL": 7,
    }
    return (1, ranks[code]) if code in ranks else (2, code)


def catalogue(request):
    q = request.GET.get("q", "").strip()[:100]
    category = request.GET.get("category", "")[:80]
    size = request.GET.get("size", "")[:80]
    color = request.GET.get("color", "")[:80]
    stock = request.GET.get("stock") == "1"
    collection = request.GET.get("collection") == "1"
    eligible = active_variants()
    if collection:
        eligible = eligible.filter(product__code__in=COLLECTION_CODES)
    if category:
        eligible = eligible.filter(product__category__code=category)
    if size:
        eligible = eligible.filter(size__code=size)
    if color:
        eligible = eligible.filter(color__code=color)
    if stock:
        eligible = eligible.filter(available_stock__gt=0)
    if q:
        eligible = filter_shop_variants(eligible, q)
    matched = eligible.filter(product_id=OuterRef("pk"))
    available = matched.filter(available_stock__gt=0)
    card_price = matched.annotate(
        sold_out=Case(When(available_stock__gt=0, then=0), default=1, output_field=IntegerField())
    ).order_by("sold_out", "selling_price", "pk")
    products = (
        product_query(eligible)
        .filter(Exists(matched))
        .annotate(
            shop_price=Subquery(card_price.values("selling_price")[:1]),
            shop_in_stock=Exists(available),
        )
    )
    sort = request.GET.get("sort", "curated")
    order = {
        "curated": ("-shop_in_stock", "code"),
        "newest": ("-created_at", "code"),
        "price_asc": ("shop_price", "code"),
        "price_desc": ("-shop_price", "code"),
    }.get(sort, ("-shop_in_stock", "code"))
    page = Paginator(products.order_by(*order), 12).get_page(request.GET.get("page"))
    current = Category.objects.filter(code=category, is_active=True).first()
    query = request.GET.copy()
    query.pop("page", None)
    return shop_render(
        request,
        "catalog/list",
        {
            "title": (
                current.name
                if current
                else ("Mẫu mới bổ sung" if collection else "Tất cả sản phẩm")
            ),
            "collection_only": collection,
            "items": [card(p) for p in page],
            "page": page,
            "query": query.urlencode(),
            "q": q,
            "selected_category": category,
            "selected_size": size,
            "selected_color": color,
            "only_stock": stock,
            "sort": sort,
            "sizes": sorted(
                Size.objects.filter(pk__in=active_variants().values("size_id")).distinct(),
                key=size_order,
            ),
            "colors": Color.objects.filter(pk__in=active_variants().values("color_id")).distinct(),
        },
    )


def product_detail(request, pk):
    p = get_object_or_404(product_query(), pk=pk)
    variants = p.shop_variants
    images = presentation(p)
    preferred = images["photo"].get("color_code", "DEN")
    selected = next(
        (v for v in variants if v.color.code == preferred and v.available_stock > 0),
        next((v for v in variants if v.available_stock > 0), variants[0] if variants else None),
    )
    color_map = {
        v.color_id: {
            "id": v.color_id,
            "name": v.color.name,
            "hex": COLOR_HEX.get(v.color.code, "#a8a79e"),
        }
        for v in variants
    }
    sizes = sorted({v.size_id: v.size for v in variants}.values(), key=size_order)
    size_choices = [{"id": size.pk, "name": size.name} for size in sizes]
    payload = [
        {
            "id": v.pk,
            "size": v.size_id,
            "color": v.color_id,
            "price": str(v.selling_price),
            "stock": v.available_stock,
            "sku": v.sku,
        }
        for v in variants
    ]
    related = (
        product_query()
        .filter(category=p.category, variants__in=active_variants())
        .exclude(pk=p.pk)
        .distinct()[:4]
    )
    return shop_render(
        request,
        "catalog/detail",
        {
            "title": p.name,
            "product": p,
            "item": card(p),
            "selected": selected,
            "variant_data": payload,
            "product_colors": list(color_map.values()),
            "product_sizes": size_choices,
            "related": [card(p) for p in related],
        },
    )
