from django import forms

from store.models import DatasetVersion, Experiment, ForecastUnit


class DemandForecastForm(forms.Form):
    dataset = forms.ModelChoiceField(queryset=DatasetVersion.objects.none(), label="Bộ dữ liệu")
    experiment = forms.ModelChoiceField(
        queryset=Experiment.objects.none(), label="Phiên bản mô hình"
    )
    target = forms.ChoiceField(label="Tháng dự báo")
    unit = forms.ModelChoiceField(queryset=ForecastUnit.objects.none(), label="Mã hàng nguồn (SKU)")

    def __init__(self, *args, datasets, dataset, targets, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dataset"].queryset = datasets
        self.fields["dataset"].widget = forms.HiddenInput()
        self.fields["experiment"].widget = forms.HiddenInput()
        self.fields["unit"].label = "Sản phẩm"
        self.fields["target"].label = "Tháng dự đoán"
        self.fields["dataset"].label_from_instance = lambda d: d.code
        self.fields["target"].choices = [
            (d.strftime("%Y-%m"), d.strftime("%m/%Y")) for d in targets
        ]
        if dataset:
            self.fields["experiment"].queryset = dataset.experiments.filter(
                status="SUCCEEDED"
            ).order_by("-pk")
            self.fields["unit"].queryset = (
                dataset.forecast_units.filter(internal_product__is_active=True)
                .select_related("internal_product")
                .order_by("label")
            )
        self.fields["unit"].label_from_instance = lambda u: f"{u.label} · {u.internal_product.name}"
        self.fields["experiment"].label_from_instance = lambda e: (
            "Cải tiến đặc trưng (v2)" if e.model_configs.get("recipes") else "Bản gốc (v1)"
        )


class StockScenarioForm(forms.Form):
    method = forms.ChoiceField(
        label="Forecast dùng tính tình huống",
        choices=[
            ("naive", "Naive"),
            ("ma3", "Moving Average (3 months)"),
            ("linear", "Linear Regression"),
            ("random_forest", "Random Forest Regression"),
        ],
    )
    stock = forms.IntegerField(label="Tồn giả định (I)", min_value=0, max_value=2_147_483_647)
    safety = forms.IntegerField(
        label="Tồn an toàn giả định (S)", min_value=0, max_value=2_147_483_647
    )
    sold = forms.IntegerField(
        label="Lượng đã bán giả định trong tháng (P)",
        min_value=0,
        max_value=2_147_483_647,
        initial=0,
    )
