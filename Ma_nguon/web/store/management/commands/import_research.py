from django.core.management.base import BaseCommand, CommandError

from store.forecast.replenishment import import_research
from store.models import User
from store.services.documents import BusinessError


class Command(BaseCommand):
    help = "Nạp kết quả nghiên cứu; không tạo giao dịch cửa hàng."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")

    def handle(self, *args, **options):
        try:
            d = import_research(User.objects.get(username=options["username"]))
        except (BusinessError, User.DoesNotExist, OSError, KeyError, ValueError) as exc:
            raise CommandError(str(exc))
        self.stdout.write(
            self.style.SUCCESS(f"{d.code}: {d.forecast_units.count()} mã, {d.status}")
        )
