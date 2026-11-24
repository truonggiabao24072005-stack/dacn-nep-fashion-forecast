from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.validators import MaxLengthValidator
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from store.forms.customers import CustomerLoginForm, CustomerProfileForm, CustomerRegistrationForm
from store.models import CustomerProfile, Role, User
from store.services.customers import claim_guest_orders, current_customer, guest_owner
from store.services.documents import BusinessError


def next_url(request):
    value = request.POST.get("next", request.GET.get("next", ""))
    if value.startswith("/") and url_has_allowed_host_and_scheme(
        value, {request.get_host()}, require_https=request.is_secure()
    ):
        return value
    return reverse("shop_account")


def signed_in_destination(request):
    if request.user.is_authenticated:
        return redirect("shop_account" if current_customer(request) else "dashboard")


def complete_login(request, user):
    claim_guest_orders(guest_owner(request), user)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    # Django rotates the session key while preserving the current shopping cart.
    request.session.pop("nep_checkout_keys", None)


@sensitive_post_parameters("password1", "password2")
@never_cache
@require_http_methods(["GET", "POST"])
def register(request):
    from store.views.common import shop_render

    destination = signed_in_destination(request)
    if destination:
        return destination
    form = CustomerRegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                data = form.cleaned_data
                user = User.objects.create_user(
                    username=data["username"],
                    full_name=data["full_name"],
                    password=data["password1"],
                    role=Role.CUSTOMER,
                    is_staff=False,
                    is_superuser=False,
                )
                CustomerProfile.objects.create(user=user, phone=data["phone"])
                complete_login(request, user)
            messages.success(request, "Đã tạo tài khoản. Chào bạn đến với Nếp!")
            return redirect(next_url(request))
        except IntegrityError:
            form.add_error("username", "Tên đăng nhập vừa được sử dụng. Bạn hãy chọn tên khác.")
        except BusinessError as exc:
            form.add_error(None, str(exc))
    return shop_render(
        request,
        "account/auth",
        {
            "title": "Tạo tài khoản",
            "form": form,
            "auth_mode": "register",
            "next": next_url(request),
        },
    )


@sensitive_post_parameters("password")
@never_cache
@require_http_methods(["GET", "POST"])
def sign_in(request):
    from store.views.common import shop_render

    destination = signed_in_destination(request)
    if destination:
        return destination
    form = CustomerLoginForm(request, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            complete_login(request, form.user)
            messages.success(request, "Đăng nhập thành công. Chào bạn trở lại!")
            return redirect(next_url(request))
        except BusinessError as exc:
            form.add_error(None, str(exc))
    return shop_render(
        request,
        "account/auth",
        {"title": "Đăng nhập", "form": form, "auth_mode": "login", "next": next_url(request)},
    )


def customer_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse("shop_login") + "?next=" + request.path)
        if not current_customer(request):
            return redirect("dashboard")
        return view(request, *args, **kwargs)

    return wrapped


@never_cache
@customer_required
@require_http_methods(["GET", "POST"])
def account(request):
    from store.views.common import shop_render

    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
    form = CustomerProfileForm(
        request.POST if request.method == "POST" else None,
        initial={"full_name": request.user.full_name, "phone": profile.phone},
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User.objects.select_for_update().get(
                pk=request.user.pk, role=Role.CUSTOMER, is_active=True
            )
            user.full_name = form.cleaned_data["full_name"]
            user.save(update_fields=["full_name", "updated_at"])
            CustomerProfile.objects.filter(user=user).update(phone=form.cleaned_data["phone"])
        messages.success(
            request, "Đã cập nhật thông tin liên hệ. Các đơn đã gửi giữ nguyên thông tin lúc đặt."
        )
        return redirect("shop_account")
    return shop_render(
        request,
        "account/profile",
        {
            "title": "Tài khoản của bạn",
            "form": form,
            "order_count": request.user.web_orders.count(),
            "recent_orders": request.user.web_orders.select_related("sale")[:3],
        },
    )


@sensitive_post_parameters("old_password", "new_password1", "new_password2")
@never_cache
@customer_required
@require_http_methods(["GET", "POST"])
def password_change(request):
    from store.views.common import shop_render

    form = PasswordChangeForm(request.user, request.POST if request.method == "POST" else None)
    for name, field in form.fields.items():
        field.widget.attrs["autocomplete"] = (
            "current-password" if name == "old_password" else "new-password"
        )
        field.widget.attrs["maxlength"] = 128
        field.validators.append(MaxLengthValidator(128))
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Đã đổi mật khẩu. Bạn vẫn đang đăng nhập trên trình duyệt này.")
        return redirect("shop_account")
    return shop_render(
        request, "account/auth", {"title": "Đổi mật khẩu", "form": form, "auth_mode": "password"}
    )


@require_POST
@never_cache
def sign_out(request):
    logout(request)
    messages.success(request, "Bạn đã đăng xuất.")
    return redirect("shop_home")
