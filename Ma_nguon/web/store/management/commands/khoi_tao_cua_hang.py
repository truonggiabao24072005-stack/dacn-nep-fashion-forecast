import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from store.models import DatasetVersion, Product, Role, SystemGuard, User
from store.services.documents import audit


class Command(BaseCommand):
    help = "Khởi tạo cửa hàng trên cơ sở dữ liệu mới, không tạo tồn hoặc lịch sử bán."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--full-name", default="Quản trị viên")

    @transaction.atomic
    def handle(self, *args, **options):
        guard = SystemGuard.objects.select_for_update().filter(pk=1).first()
        if (
            guard
            and guard.data_mode == "OPERATIONAL"
            and User.objects.filter(role=Role.ADMIN, is_active=True).exists()
        ):
            self.stdout.write(
                "Cửa hàng đã được khởi tạo. Không thay tài khoản, mốc ghi sổ hoặc dữ liệu."
            )
            return
        if (
            guard
            or User.objects.exists()
            or Product.objects.exists()
            or DatasetVersion.objects.exists()
        ):
            raise CommandError(
                "Cơ sở dữ liệu đã có dữ liệu. Cần cơ sở dữ liệu mới để khởi tạo cửa hàng."
            )
        username = options["username"].strip().lower()
        full_name = options["full_name"].strip()
        candidate = User(username=username, full_name=full_name, role=Role.ADMIN)
        password = os.environ.get("STORE_ADMIN_PASSWORD", "")
        if not username or not full_name or not password:
            raise CommandError("Cần tên tài khoản, họ tên và biến môi trường STORE_ADMIN_PASSWORD.")
        try:
            candidate.full_clean(exclude=["password"])
            validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        SystemGuard.objects.create(pk=1, data_mode="OPERATIONAL")
        admin = User.objects.create_user(
            username, password=password, full_name=full_name, role=Role.ADMIN
        )
        audit(admin, "INITIALIZE_STORE", admin, {"username": username})
        self.stdout.write(
            "Đã khởi tạo cửa hàng và tài khoản quản trị. Tiếp tục khai báo hàng hóa và nhập tồn thực tế."
        )
