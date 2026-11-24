from django import forms

from store.services.payment_preferences import PAYMENT_METHOD_CHOICES


class CheckoutForm(forms.Form):
    delivery_address = forms.CharField(
        label="Địa chỉ giao hàng",
        required=False,
        min_length=10,
        max_length=350,
        widget=forms.TextInput(attrs={"autocomplete": "street-address"}),
        help_text="Để trống nếu nhận tại cửa hàng. Giao hàng sử dụng thanh toán VNPAY.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from store.services.vnpay import gateway_available

        if not gateway_available():
            self.fields.pop("delivery_address")
            self.fields["payment_method"].choices = [
                (code, label) for code, label in PAYMENT_METHOD_CHOICES if code != "VNPAY"
            ]

    payment_method = forms.ChoiceField(
        label="Phương thức thanh toán",
        choices=PAYMENT_METHOD_CHOICES,
        initial="CASH",
        widget=forms.RadioSelect(attrs={"class": "payment-methods"}),
    )
    customer_name = forms.CharField(
        label="Họ và tên",
        min_length=2,
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "name", "placeholder": "Tên người nhận hàng"}
        ),
    )
    phone = forms.CharField(
        label="Số điện thoại",
        max_length=25,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "tel",
                "inputmode": "tel",
                "placeholder": "Số điện thoại để cửa hàng xác nhận",
            }
        ),
    )
    note = forms.CharField(
        label="Lời nhắn cho cửa hàng",
        max_length=1000,
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Ví dụ: thời điểm bạn dự kiến ghé nhận hàng"}
        ),
    )
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    quote = forms.CharField(widget=forms.HiddenInput, max_length=12000)

    def clean_phone(self):
        import re

        value = re.sub(r"[\s.()-]", "", self.cleaned_data["phone"])
        if not re.fullmatch(r"(?:0|\+84)[0-9]{8,10}", value):
            raise forms.ValidationError(
                "Nhập số điện thoại Việt Nam hợp lệ, bắt đầu bằng 0 hoặc +84."
            )
        return value
