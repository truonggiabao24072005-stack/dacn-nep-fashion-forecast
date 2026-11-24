from django import forms

from store.models import Customer, Supplier, Variant


class DocumentVersionForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class SaleForm(forms.Form):
    customer = forms.ModelChoiceField(
        label="Khách hàng",
        queryset=Customer.objects.filter(is_active=True),
        required=False,
        empty_label="Khách lẻ, không tạo hồ sơ",
    )


class ReceiptForm(forms.Form):
    supplier = forms.ModelChoiceField(
        label="Nhà cung cấp", queryset=Supplier.objects.filter(is_active=True)
    )
    delivery_reference = forms.CharField(
        label="Tham chiếu giao hàng", max_length=100, required=False
    )
    note = forms.CharField(
        label="Ghi chú nhận hàng", widget=forms.Textarea(attrs={"rows": 3}), required=False
    )


class AdjustmentForm(forms.Form):
    kind = forms.ChoiceField(
        label="Loại phiếu",
        choices=[("OPENING", "Tồn đầu kỳ"), ("COUNT", "Kiểm đếm và điều chỉnh")],
    )
    reason = forms.CharField(label="Lý do và căn cứ", widget=forms.Textarea(attrs={"rows": 3}))
    source_reference = forms.CharField(label="Tham chiếu kiểm đếm", max_length=100, required=False)


class DocumentLineForm(DocumentVersionForm):
    variant = forms.ModelChoiceField(
        label="Biến thể",
        queryset=Variant.objects.select_related("product", "size", "color", "balance").filter(
            is_active=True
        ),
    )
    quantity = forms.IntegerField(label="Số lượng", min_value=1, max_value=2_147_483_647)
    unit_cost = forms.DecimalField(
        label="Giá nhập một đơn vị (đồng)",
        min_value=0,
        max_digits=18,
        decimal_places=0,
        required=False,
    )

    def __init__(self, *args, kind="sale", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["variant"].label_from_instance = (
            lambda v: f"{v.sku} · {v.product.name} · {v.size.name}/{v.color.name} · tồn {v.balance.quantity}"
        )
        if kind == "receipt":
            self.fields["unit_cost"].required = True
        else:
            del self.fields["unit_cost"]
        if kind == "adjustment":
            self.fields["variant"].queryset = Variant.objects.select_related(
                "product", "size", "color", "balance"
            )
            self.fields["quantity"] = forms.IntegerField(
                label="Số thực đếm", min_value=0, max_value=2_147_483_647
            )


class ConfirmDocumentForm(DocumentVersionForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    method = forms.ChoiceField(
        label="Phương thức thanh toán",
        choices=[("CASH", "Tiền mặt"), ("TRANSFER", "Chuyển khoản, nhân viên xác nhận")],
        widget=forms.RadioSelect(attrs={"class": "payment-methods"}),
        required=False,
    )
    cash_received = forms.DecimalField(
        label="Tiền khách đưa (đồng)", decimal_places=0, max_digits=18, min_value=0, required=False
    )
    transfer_ack = forms.BooleanField(
        label="Đã đối chiếu khoản chuyển với tổng đơn", required=False
    )
    reference = forms.CharField(label="Tham chiếu khoản chuyển", max_length=100, required=False)


class CorrectionForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(label="Lý do sửa sai", widget=forms.Textarea(attrs={"rows": 3}))
    evidence = forms.CharField(label="Căn cứ đối soát", widget=forms.Textarea(attrs={"rows": 3}))
    goods_ack = forms.BooleanField(label="Đã thu hồi đủ hàng còn bán được", required=False)
    financial_ack = forms.BooleanField(label="Đã đối soát tiền thực tế", required=False)
