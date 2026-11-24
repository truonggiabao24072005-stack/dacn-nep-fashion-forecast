from django import forms
from django.forms import modelform_factory

from store.services.catalog import CATALOGS


def build_catalog_form(kind, data=None, instance=None):
    model, _, fields = CATALOGS[kind]
    form_class = modelform_factory(
        model,
        fields=fields,
        widgets={
            "note": forms.Textarea(attrs={"rows": 3}),
            "address": forms.Textarea(attrs={"rows": 3}),
        },
    )
    form = form_class(data=data, instance=instance)
    form.fields["version"] = forms.IntegerField(
        widget=forms.HiddenInput, initial=instance.version if instance else 1, min_value=1
    )
    for name in ["code", "sku"]:
        if name in form.fields:
            form.fields[name].max_length = 80
    return form
