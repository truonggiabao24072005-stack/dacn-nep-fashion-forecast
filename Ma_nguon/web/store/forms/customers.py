import re

from django import forms
from django.contrib.auth.password_validation import validate_password

from store.models import Role, User
from store.services.authentication import limited_authenticate


def clean_phone(value):
    value = re.sub(r"[\s.()-]", "", value)
    if not re.fullmatch(r"(?:0|\+84)[0-9]{8,10}", value):
        raise forms.ValidationError("Nhập số điện thoại Việt Nam hợp lệ, bắt đầu bằng 0 hoặc +84.")
    return value


class CustomerProfileForm(forms.Form):
    full_name = forms.CharField(
        label="Họ và tên",
        min_length=2,
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    phone = forms.CharField(
        label="Số điện thoại",
        max_length=25,
        widget=forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
    )

    def clean_phone(self):
        return clean_phone(self.cleaned_data["phone"])


class CustomerRegistrationForm(CustomerProfileForm):
    username = forms.RegexField(
        label="Tên đăng nhập",
        regex=r"^[a-zA-Z0-9_.@+-]{3,150}$",
        max_length=150,
        help_text="Từ 3 ký tự; dùng chữ không dấu, số hoặc dấu . _ @ + -",
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "autocapitalize": "none", "spellcheck": "false"}
        ),
    )
    password1 = forms.CharField(
        label="Mật khẩu",
        strip=False,
        max_length=128,
        help_text="Ít nhất 10 ký tự, tránh mật khẩu phổ biến, toàn chữ số hoặc giống tên đăng nhập.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Nhập lại mật khẩu",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    field_order = ["full_name", "username", "phone", "password1", "password2"]

    def clean_username(self):
        value = self.cleaned_data["username"].lower()
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError("Tên đăng nhập đã được sử dụng. Bạn hãy chọn tên khác.")
        return value

    def clean(self):
        data = super().clean()
        if data.get("password1"):
            validate_password(
                data["password1"],
                User(username=data.get("username", ""), full_name=data.get("full_name", "")),
            )
        if (
            data.get("password1")
            and data.get("password2")
            and data["password1"] != data["password2"]
        ):
            self.add_error("password2", "Hai mật khẩu chưa trùng nhau.")
        return data


def check_customer_login(request, username, password):
    return limited_authenticate(request, username, password, [Role.CUSTOMER])


class CustomerLoginForm(forms.Form):
    username = forms.CharField(
        label="Tên đăng nhập",
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "autocapitalize": "none", "spellcheck": "false"}
        ),
    )
    password = forms.CharField(
        label="Mật khẩu",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request, *args, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get("username") and data.get("password"):
            self.user, error = check_customer_login(
                self.request, data["username"].strip().lower(), data["password"]
            )
            if error:
                raise forms.ValidationError(error)
        return data
