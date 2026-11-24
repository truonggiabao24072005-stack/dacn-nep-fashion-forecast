from django import forms


class ShopLocationForm(forms.Form):
    address = forms.CharField(
        label="Địa chỉ cửa hàng",
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"autocomplete": "street-address"}),
        help_text="Nhập số nhà, tên đường, phường/xã và tỉnh/thành. Để trống để ẩn địa chỉ.",
    )
    is_example = forms.BooleanField(
        label="Địa chỉ minh họa",
        required=False,
        help_text="Bật tùy chọn này nếu địa chỉ chỉ dùng để trình diễn đồ án.",
    )

    def clean_address(self):
        address = " ".join(self.cleaned_data["address"].split())
        if address and len(address) < 8:
            raise forms.ValidationError("Vui lòng nhập địa chỉ đầy đủ.")
        return address
