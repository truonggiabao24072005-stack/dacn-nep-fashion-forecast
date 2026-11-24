"""Persistent, role-scoped login throttling shared by both sign-in pages."""

from datetime import timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from store.models import CustomerLoginAttempt


@transaction.atomic
def limited_authenticate(request, username, password, roles, *, scope="customer"):
    ip = request.META.get("REMOTE_ADDR", "")[:64]
    salt = "nep.login" if scope == "customer" else "nep.staff.login"
    buckets = []
    now = timezone.now()
    # Every request locks its IP before its username/IP pair. An already blocked
    # IP therefore cannot keep creating new pair rows with arbitrary usernames.
    specs = [(salt + ".ip", ip, 30), (salt + ".pair", ip + "|" + username, 8)]
    for namespace, identifier, limit in specs:
        key = salted_hmac(namespace, identifier, algorithm="sha256").hexdigest()
        CustomerLoginAttempt.objects.get_or_create(key=key)
        bucket = CustomerLoginAttempt.objects.select_for_update().get(pk=key)
        if now - bucket.window_start >= timedelta(minutes=15):
            bucket.failures = 0
            bucket.window_start = now
        if bucket.failures >= limit:
            return None, "Bạn đã thử quá nhiều lần. Vui lòng thử lại sau 15 phút."
        buckets.append((bucket, limit))
    user = authenticate(request, username=username, password=password)
    allowed = user is not None and user.is_active and user.role in roles
    for bucket, limit in buckets:
        if not allowed:
            bucket.failures += 1
        elif limit == 8:
            bucket.failures = 0
        bucket.save(update_fields=["failures", "window_start"])
    return (user, "") if allowed else (None, "Tên đăng nhập hoặc mật khẩu chưa đúng.")
