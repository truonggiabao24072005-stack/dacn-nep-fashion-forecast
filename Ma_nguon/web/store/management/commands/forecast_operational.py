from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from store.forecast.demand import generate_operational
from store.forecast.replenishment import month_add, month_parse
from store.models import User
from store.services.documents import BusinessError


class Command(BaseCommand):
    help = "Tạo dự báo từ dữ liệu cửa hàng đã đóng kỳ, ngoài giao dịch kho."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--cutoff", help="YYYY-MM, mặc định tháng trước")

    def handle(self, *args, **options):
        try:
            cutoff = (
                month_parse(options["cutoff"])
                if options["cutoff"]
                else month_add(timezone.localdate().replace(day=1), -1)
            )
            ds = generate_operational(User.objects.get(username=options["username"]), cutoff)
        except (BusinessError, User.DoesNotExist) as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS("Đã tạo " + ds.code))
