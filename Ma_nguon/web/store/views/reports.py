from django.shortcuts import render
from django.utils import timezone

from store.forms.reports import DateRangeForm
from store.models import Role
from store.services.reports import sales_report
from store.views.common import role_required


@role_required(Role.ADMIN)
def report(request):
    today = timezone.localdate()
    form = DateRangeForm(
        request.GET or None, initial={"start": today.replace(day=1), "end": today, "group": "day"}
    )
    result = None
    if not request.GET:
        result = sales_report(request.user, today.replace(day=1), today)
    elif form.is_valid():
        result = sales_report(request.user, **form.cleaned_data)
    return render(
        request,
        "store/reports/sales.html",
        {"title": "Báo cáo bán hàng", "form": form, "result": result},
    )
