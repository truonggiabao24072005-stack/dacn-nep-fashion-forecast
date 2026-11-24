from django import forms

from store.models import ShopPost


class ShopPostForm(forms.ModelForm):
    publish = forms.BooleanField(label="Hiển thị trên trang Tin tức", required=False)

    class Meta:
        model = ShopPost
        fields = ("title", "summary", "body")
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 3}),
            "body": forms.Textarea(attrs={"rows": 10}),
        }
