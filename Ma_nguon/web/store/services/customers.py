from django.db import transaction
from django.utils.crypto import salted_hmac

from store.models import Role, WebGuestOwner, WebOrder
from store.services.documents import BusinessError


def account_owner(user):
    return salted_hmac("nep.customer.order", str(user.pk), algorithm="sha256").hexdigest()


def guest_owner(request):
    if not request.session.session_key:
        return ""
    return salted_hmac(
        "nep.guest.order", request.session.session_key, algorithm="sha256"
    ).hexdigest()


def current_customer(request):
    u = request.user
    return u if u.is_authenticated and u.is_active and u.role == Role.CUSTOMER else None


@transaction.atomic
def claim_guest_orders(owner_hash, user):
    if not owner_hash:
        return
    WebGuestOwner.objects.get_or_create(owner_hash=owner_hash)
    identity = WebGuestOwner.objects.select_for_update().get(pk=owner_hash)
    if identity.account_id and identity.account_id != user.pk:
        raise BusinessError(
            "Phiên này đã được gắn với tài khoản khác. Vui lòng mở lại trình duyệt."
        )
    identity.account = user
    identity.save(update_fields=["account"])
    WebOrder.objects.filter(owner_hash=owner_hash, account__isnull=True).update(account=user)
