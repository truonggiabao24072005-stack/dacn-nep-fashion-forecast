import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from store.models import Role, User, Variant
from store.pricing import rounded_selling_price
from store.services.catalog import save_catalog


class Command(BaseCommand):
    help = "Làm tròn giá bán hiện hành đến 1.000 đồng và ghi nhật ký cập nhật danh mục."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            actor = User.objects.get(
                username=options["username"], role=Role.ADMIN, is_active=True
            )
        except User.DoesNotExist as exc:
            raise CommandError("Cần tài khoản quản trị đang hoạt động.") from exc

        changes = []
        products = list(
            Variant.objects.filter(
                product__is_active=True,
                product__category__is_active=True,
                product__brand__is_active=True,
                is_active=True,
                size__is_active=True,
                color__is_active=True,
                selling_price__gt=0,
            )
            .select_related("product", "size", "color")
            .order_by("product_id", "pk")
        )
        for variant in products:
            price = rounded_selling_price(variant.selling_price)
            if price == variant.selling_price:
                continue
            changes.append(
                {"sku": variant.sku, "before": str(variant.selling_price), "after": str(price)}
            )
            if options["apply"]:
                fields = {
                    name: getattr(variant, name)
                    for name in (
                        "sku", "product", "size", "color", "low_stock_threshold", "is_active"
                    )
                }
                fields["selling_price"] = price
                save_catalog(actor, "variants", fields, pk=variant.pk, version=variant.version)

        self.stdout.write(json.dumps(
            {"currency": "VND", "round_to": 1000, "applied": options["apply"], "changes": changes},
            ensure_ascii=False,
        ))
