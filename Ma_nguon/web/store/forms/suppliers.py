from django import forms
from django.utils import timezone

from store.forecast.replenishment import sellable_variants
from store.models import SupplierOrder


class SupplierOrderForm(forms.ModelForm):
    class Meta:
        model = SupplierOrder
        fields = ["reference", "supplier", "variant", "ordered_qty", "expected_on"]
        widgets = {"expected_on": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = self.fields["supplier"].queryset.filter(is_active=True)
        self.fields["variant"].queryset = sellable_variants().select_related(
            "product", "size", "color"
        )

    def clean_expected_on(self):
        value = self.cleaned_data["expected_on"]
        if value < timezone.localdate():
            raise forms.ValidationError("Ngày dự kiến nhận không được ở quá khứ.")
        return value

    def clean_ordered_qty(self):
        value = self.cleaned_data["ordered_qty"]
        if not value:
            raise forms.ValidationError("Số lượng đặt phải lớn hơn 0.")
        return value


class SupplierDeliveryForm(forms.Form):
    delivery_reference = forms.CharField(label="Mã phiếu giao", max_length=100)
    quantity = forms.IntegerField(
        label="Số lượng đạt để nhập kho", min_value=1, max_value=2147483647
    )
    unit_cost = forms.DecimalField(
        label="Giá nhập mỗi đơn vị", min_value=1, max_digits=18, decimal_places=0
    )
    checked = forms.BooleanField(
        label="Đã đối chiếu mã hàng, cỡ, màu và tình trạng của số lượng đạt"
    )
    request_key = forms.UUIDField(widget=forms.HiddenInput)


class SkuReplenishmentForm(forms.Form):
    variant = forms.ModelChoiceField(
        label="Biến thể", queryset=sellable_variants().select_related("product", "size", "color")
    )
    lead_days = forms.IntegerField(
        label="Thời gian giao hàng (ngày)", min_value=1, max_value=90, initial=14
    )
    safety = forms.IntegerField(
        label="Tồn an toàn theo biến thể", min_value=0, max_value=2147483647, initial=0
    )
    observed = forms.BooleanField(
        label="Đã đối chiếu đủ dữ liệu bán 30 ngày của biến thể", required=True
    )
