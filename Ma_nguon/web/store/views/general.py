from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from store.models import STAFF_ROLES, AuditEvent, Role
from store.views.common import role_required


@role_required(Role.ADMIN)
def audit_log(request):
    qs = AuditEvent.objects.select_related("actor")
    q = request.GET.get("q", "")
    if q:
        qs = qs.filter(
            Q(action__icontains=q) | Q(object_type__icontains=q) | Q(object_id__icontains=q)
        )
    return render(
        request,
        "store/audit.html",
        {
            "title": "Nhật ký nghiệp vụ",
            "page": Paginator(qs, 30).get_page(request.GET.get("page")),
            "q": q,
        },
    )


@role_required(*STAFF_ROLES)
def guide(request):
    return render(request, "store/guide.html", {"title": "Hướng dẫn sử dụng"})
