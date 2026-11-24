from datetime import date

from django import forms


class DateRangeForm(forms.Form):
    start = forms.DateField(label="Từ ngày", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Đến ngày", widget=forms.DateInput(attrs={"type": "date"}))
    group = forms.ChoiceField(label="Nhóm theo", choices=[("day", "Ngày"), ("month", "Tháng")])

    def clean(self):
        values = super().clean()
        if values.get("start") and values.get("end"):
            if values["end"] == date.max:
                raise forms.ValidationError(
                    "Ngày kết thúc nằm ngoài phạm vi có thể lập báo cáo. Vui lòng chọn ngày khác."
                )
            if values["start"] > values["end"]:
                raise forms.ValidationError("Ngày bắt đầu không được sau ngày kết thúc.")
            if (values["end"] - values["start"]).days > 3660:
                raise forms.ValidationError("Vui lòng chọn khoảng thời gian không quá 10 năm.")
        return values
