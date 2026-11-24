from django.core.management.base import BaseCommand, CommandError

from store.models import StockBalance, User
from store.services.reports import reconciliation


class Command(BaseCommand):
    help = "Đối chiếu số dư mọi SKU với tổng sổ biến động."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")

    def handle(self, *args, **options):
        issues = list(reconciliation(User.objects.get(username=options["username"])))
        if issues:
            raise CommandError(
                "; ".join(f"{b.variant.sku}: số dư {b.quantity}, sổ {b.ledger}" for b in issues)
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Đối chiếu đạt: {StockBalance.objects.count()} SKU, không có chênh lệch."
            )
        )
