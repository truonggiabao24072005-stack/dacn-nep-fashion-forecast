from decimal import Decimal
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from store.forms.documents import (
    AdjustmentForm,
    ConfirmDocumentForm,
    CorrectionForm,
    DocumentLineForm,
    ReceiptForm,
    SaleForm,
)
from store.models import Role, Status, Variant, WebOrder
from store.services.documents import (
    DOCUMENTS,
    BusinessError,
    authorize,
    cancel_draft,
    confirm_document,
    correct_document,
    create_document,
    owned_document,
    refresh_prices,
    roles_for,
    set_line,
    update_header,
)
from store.validation import positive_identifier
from store.views.common import role_required, show_error

DOCUMENT_TITLES = {
    "sale": "Đơn bán hàng",
    "receipt": "Phiếu nhập hàng",
    "adjustment": "Tồn đầu kỳ và kiểm đếm",
    "correction": "Chứng từ sửa sai",
}


@login_required
def documents(request, kind):
    if kind not in DOCUMENTS:
        raise Http404
    authorize(request.user, roles_for(kind))
    qs = DOCUMENTS[kind].objects.select_related("created_by")
    if request.user.role != Role.ADMIN:
        qs = qs.filter(created_by=request.user)
    if request.GET.get("status") in Status.values:
        qs = qs.filter(status=request.GET["status"])
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(code__icontains=q)
    return render(
        request,
        "store/documents/list.html",
        {
            "title": DOCUMENT_TITLES[kind],
            "kind": kind,
            "page": Paginator(qs, 20).get_page(request.GET.get("page")),
            "statuses": Status.choices,
            "q": q,
        },
    )


@login_required
def document_new(request, kind):
    if kind not in ["sale", "receipt", "adjustment"]:
        raise Http404
    authorize(request.user, roles_for(kind))
    form = {"sale": SaleForm, "receipt": ReceiptForm, "adjustment": AdjustmentForm}[kind](
        request.POST if request.method == "POST" else None
    )
    if request.method == "POST" and form.is_valid():
        try:
            doc = create_document(request.user, kind, form.cleaned_data)
            return redirect("document", kind=kind, pk=doc.pk)
        except (BusinessError, ValidationError, IntegrityError) as exc:
            show_error(form, exc)
    return render(
        request,
        "store/shared/form.html",
        {
            "title": "Tạo " + DOCUMENT_TITLES[kind].lower(),
            "form": form,
            "back": reverse("documents", args=[kind]),
            "hint": "Nháp chưa giữ hàng và chưa làm thay đổi tồn kho.",
        },
    )


@login_required
def document_detail(request, kind, pk):
    if kind not in DOCUMENTS:
        raise Http404
    try:
        doc = owned_document(request.user, kind, pk)
    except ObjectDoesNotExist:
        raise Http404
    lines = []
    if kind != "correction":
        lines = list(
            doc.lines.select_related(
                "variant__product", "variant__size", "variant__color"
            ).order_by("pk")
        )
    web_order = WebOrder.objects.filter(sale=doc).first() if kind == "sale" else None
    preferred_method = web_order.payment_preference if web_order else ""
    context = {
        "web_order": web_order,
        "title": doc.code,
        "doc": doc,
        "kind": kind,
        "lines": lines,
        "payment": getattr(doc, "payment", None),
        "line_form": DocumentLineForm(kind=kind, initial={"version": doc.version}),
        "confirm_form": ConfirmDocumentForm(
            initial={
                "version": doc.version,
                "request_key": uuid4(),
                "cash_received": getattr(doc, "total_amount", 0),
                "method": preferred_method if preferred_method in ["CASH", "TRANSFER"] else "",
            }
        ),
        "corrections": (
            doc.corrections.filter(status=Status.POSTED) if kind in ["sale", "receipt"] else []
        ),
    }
    if kind in ["sale", "receipt"] and doc.status == Status.DRAFT:
        initial = (
            {"customer": doc.customer_id}
            if kind == "sale"
            else {
                "supplier": doc.supplier_id,
                "delivery_reference": doc.delivery_reference,
                "note": doc.note,
            }
        )
        context["header_form"] = (SaleForm if kind == "sale" else ReceiptForm)(initial=initial)
    return render(request, "store/documents/detail.html", context)


@login_required
@require_POST
def document_action(request, kind, pk):
    if kind not in ["sale", "receipt", "adjustment"]:
        raise Http404
    authorize(request.user, roles_for(kind))
    action = request.POST.get("action")
    try:
        if action == "header":
            if kind not in ["sale", "receipt"]:
                raise Http404
            form = (SaleForm if kind == "sale" else ReceiptForm)(request.POST)
            if not form.is_valid():
                raise BusinessError(
                    "Thông tin đầu phiếu không hợp lệ. Kiểm tra khách hàng hoặc nhà cung cấp."
                )
            update_header(request.user, kind, pk, request.POST.get("version"), form.cleaned_data)
            messages.success(request, "Đã cập nhật thông tin đầu phiếu nháp.")
        elif action == "line":
            form = DocumentLineForm(request.POST, kind=kind)
            if not form.is_valid():
                raise BusinessError(
                    " ".join(
                        f'{form.fields[k].label}: {" ".join(v)}' for k, v in form.errors.items()
                    )
                )
            c = form.cleaned_data
            set_line(
                request.user,
                kind,
                pk,
                c["version"],
                c["variant"],
                c["quantity"],
                c.get("unit_cost"),
            )
            messages.success(request, "Đã cập nhật dòng nháp. Kho chưa thay đổi.")
        elif action == "remove":
            identifier = positive_identifier(request.POST.get("variant"))
            if identifier is None:
                raise Http404
            variant = get_object_or_404(Variant, pk=identifier)
            set_line(request.user, kind, pk, request.POST.get("version"), variant, 0, remove=True)
            messages.success(request, "Đã bỏ dòng khỏi nháp.")
        elif action == "refresh":
            if kind != "sale":
                raise Http404
            refresh_prices(request.user, pk, request.POST.get("version"))
            messages.success(
                request, "Đã cập nhật bảng giá. Hãy kiểm tra tổng mới trước khi hoàn tất."
            )
        elif action == "confirm":
            form = ConfirmDocumentForm(request.POST)
            if not form.is_valid():
                raise BusinessError(
                    "Thông tin xác nhận không hợp lệ. Kiểm tra số tiền và tải lại nếu cần."
                )
            c = form.cleaned_data
            pay = (
                {
                    k: (str(c[k]) if isinstance(c.get(k), Decimal) else c.get(k))
                    for k in ["method", "cash_received", "transfer_ack", "reference"]
                }
                if kind == "sale"
                else None
            )
            confirm_document(request.user, kind, pk, c["version"], c["request_key"], pay)
            messages.success(request, "Đã ghi nhận chứng từ và tồn kho cùng nhau.")
        elif action == "cancel":
            cancel_draft(
                request.user, kind, pk, request.POST.get("version"), request.POST.get("reason", "")
            )
            messages.success(request, "Đã hủy nháp; không phát sinh biến động kho.")
        else:
            return HttpResponseBadRequest("Thao tác không hợp lệ.")
    except (BusinessError, ValidationError, IntegrityError) as exc:
        messages.error(
            request,
            (
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else (
                    str(exc)
                    if not isinstance(exc, IntegrityError)
                    else "Dữ liệu thay đổi hoặc xung đột. Hãy tải lại để đối chiếu."
                )
            ),
        )
    except ObjectDoesNotExist:
        raise Http404
    return redirect("document", kind=kind, pk=pk)


@role_required(Role.ADMIN)
def correction(request, kind, pk):
    if kind not in ["sale", "receipt"]:
        raise Http404
    doc = get_object_or_404(DOCUMENTS[kind], pk=pk)
    returning = kind == "sale" and request.GET.get("tra-hang") == "1"
    form = CorrectionForm(
        request.POST if request.method == "POST" else None, initial={"request_key": uuid4()}
    )
    if request.method == "POST" and form.is_valid():
        try:
            c = form.cleaned_data.copy()
            key = c.pop("request_key")
            result = correct_document(request.user, kind, pk, key, **c)
            messages.success(request, "Đã ghi chứng từ bù trừ toàn bộ; chứng từ gốc giữ nguyên.")
            return redirect("document", kind="correction", pk=result.pk)
        except (BusinessError, ValidationError, IntegrityError) as exc:
            show_error(form, exc)
    return render(
        request,
        "store/shared/form.html",
        {
            "title": ("Trả toàn bộ đơn " if returning else "Sửa sai toàn bộ ") + doc.code,
            "form": form,
            "back": reverse("document", args=[kind, pk]),
            "hint": (
                "Đối chiếu đơn gốc, kiểm tra toàn bộ hàng còn bán được và hoàn tiền trước khi xác nhận. "
                "Nếu khách đổi mẫu hoặc cỡ, lập đơn bán mới sau khi ghi nhận hàng trả."
                if returning
                else "Đảo bán cần thu hồi đủ hàng còn bán được và đối soát tiền. Đảo nhập cần đủ tồn."
            ),
        },
    )
