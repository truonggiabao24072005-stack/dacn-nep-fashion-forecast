from django import forms

from store.models import STAFF_ROLE_CHOICES


class EmployeeForm(forms.Form):
    username = forms.RegexField(
        label="Tên đăng nhập", regex=r"^[a-zA-Z0-9_.@+-]{3,150}$", max_length=150
    )
    full_name = forms.CharField(label="Họ tên", max_length=150)
    role = forms.ChoiceField(label="Vai trò", choices=[("", "Chọn vai trò"), *STAFF_ROLE_CHOICES])
    is_active = forms.BooleanField(label="Được phép sử dụng", required=False, initial=True)
    new_password = forms.CharField(
        label="Mật khẩu mới",
        widget=forms.PasswordInput,
        required=False,
        strip=False,
        max_length=128,
        help_text="Ít nhất 10 ký tự. Khi chỉnh sửa, để trống nếu giữ mật khẩu hiện tại.",
    )
    version = forms.IntegerField(widget=forms.HiddenInput, initial=1, min_value=1)
