from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from store.forms.employees import EmployeeForm
from store.models import STAFF_ROLES, Role, User
from store.services.catalog import save_user
from store.services.documents import BusinessError
from store.views.common import role_required, show_error


@role_required(Role.ADMIN)
def employees(request):
    return render(
        request,
        "store/employees/list.html",
        {
            "title": "Tài khoản nhân viên",
            "employees": User.objects.filter(role__in=STAFF_ROLES).order_by("username"),
        },
    )


@role_required(Role.ADMIN)
def employee_edit(request, pk=None):
    obj = get_object_or_404(User, pk=pk, role__in=STAFF_ROLES) if pk else None
    initial = (
        {f: getattr(obj, f) for f in ["username", "full_name", "role", "is_active", "version"]}
        if obj
        else {}
    )
    form = EmployeeForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            save_user(request.user, form.cleaned_data, pk, form.cleaned_data["version"])
            messages.success(request, "Đã lưu tài khoản và quyền sử dụng.")
            return redirect("employees")
        except (BusinessError, ValidationError, IntegrityError) as exc:
            show_error(form, exc)
    return render(
        request,
        "store/shared/form.html",
        {
            "title": "Cập nhật nhân viên" if pk else "Cấp tài khoản nhân viên",
            "form": form,
            "back": reverse("employees"),
            "hint": "Mật khẩu được băm. Thay quyền có hiệu lực ở yêu cầu tiếp theo.",
        },
    )
