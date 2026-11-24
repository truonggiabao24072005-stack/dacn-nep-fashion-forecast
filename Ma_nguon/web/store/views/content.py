from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from store.forms.content import ShopPostForm
from store.models import Role, ShopPost
from store.views.common import role_required, shop_render


def about(request):
    return shop_render(request, "content/about", {"title": "Về Nếp"})


def news(request):
    posts = ShopPost.objects.filter(published_at__lte=timezone.now()).order_by(
        "-published_at", "-pk"
    )
    page = Paginator(posts, 9).get_page(request.GET.get("page"))
    return shop_render(request, "content/news", {"title": "Tin tức", "page": page})


def article(request, pk):
    post = get_object_or_404(ShopPost, pk=pk, published_at__lte=timezone.now())
    return shop_render(request, "content/article", {"title": post.title, "post": post})


@role_required(Role.ADMIN)
def manage_posts(request):
    page = Paginator(ShopPost.objects.order_by("-updated_at", "-pk"), 20).get_page(
        request.GET.get("page")
    )
    return render(request, "store/content/manage.html", {"title": "Tin tức cửa hàng", "page": page})


@role_required(Role.ADMIN)
@transaction.atomic
def edit_post(request, pk=None):
    submitted = request.method == "POST"
    posts = ShopPost.objects.select_for_update() if submitted else ShopPost.objects.all()
    post = get_object_or_404(posts, pk=pk) if pk else None
    data = request.POST if submitted else None
    form = ShopPostForm(data, instance=post, initial={"publish": bool(post and post.published_at)})
    if submitted and form.is_valid():
        item = form.save(commit=False)
        if form.cleaned_data["publish"]:
            item.published_at = item.published_at or timezone.now()
        else:
            item.published_at = None
        item.save()
        messages.success(request, "Đã đăng tin." if item.published_at else "Đã lưu bản nháp.")
        return redirect("shop_manage_posts")
    return render(
        request,
        "store/content/edit.html",
        {
            "title": "Chỉnh sửa tin" if post else "Soạn tin mới",
            "form": form,
        },
    )
