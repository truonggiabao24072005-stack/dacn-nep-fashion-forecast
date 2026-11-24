from django import forms
from django.contrib.auth.forms import AuthenticationForm

from store.models import STAFF_ROLES
from store.services.authentication import limited_authenticate


class EmployeeLoginForm(AuthenticationForm):
    username = forms.CharField(label="Tên đăng nhập", max_length=150)
    password = forms.CharField(
        label="Mật khẩu",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username and password:
            self.user_cache, error = limited_authenticate(
                self.request, username, password, STAFF_ROLES, scope="staff"
            )
            if error:
                raise forms.ValidationError(error, code="invalid_login")
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role not in STAFF_ROLES:
            raise forms.ValidationError(
                "Trang này dành cho nhân viên. Khách mua hàng vui lòng đăng nhập tại mục Tài khoản."
            )
