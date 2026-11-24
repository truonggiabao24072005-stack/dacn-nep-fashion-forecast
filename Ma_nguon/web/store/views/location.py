from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from store.forms.location import ShopLocationForm
from store.models import Role, ShopLocation
from store.services.documents import audit, authorize
from store.views.common import role_required


@role_required(Role.ADMIN)
@require_http_methods(["GET", "POST"])
def manage_location(request):
    saved = ShopLocation.objects.filter(pk=1).first()
    form = ShopLocationForm(
        request.POST if request.method == "POST" else None,
        initial={"address": saved.address, "is_example": saved.is_example} if saved else None,
    )
    if request.method == "POST" and form.is_valid():
        address = form.cleaned_data["address"]
        is_example = bool(address and form.cleaned_data["is_example"])
        with transaction.atomic():
            actor = authorize(request.user, [Role.ADMIN], lock=True)
            location, _ = ShopLocation.objects.select_for_update().get_or_create(pk=1)
            if (location.address, location.is_example) != (address, is_example):
                location.address = address
                location.is_example = is_example
                location.save(update_fields=["address", "is_example"])
                audit(
                    actor,
                    "UPDATE_SHOP_LOCATION",
                    location,
                    {"address": address, "is_example": is_example},
                )
        messages.success(request, "Đã lưu địa chỉ cửa hàng.")
        return redirect("manage_shop_location")
    return render(
        request, "store/settings/location.html", {"title": "Địa chỉ cửa hàng", "form": form}
    )
