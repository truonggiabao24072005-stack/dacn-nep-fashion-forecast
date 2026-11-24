import json

from django.core.management.base import BaseCommand, CommandError

from store.models import User
from store.services.catalog_import import import_catalog, validate_bundle
from store.services.documents import BusinessError


class Command(BaseCommand):
    help = "Đối chiếu và nhập SKU nguồn cùng liên kết ảnh; mặc định chỉ kiểm tra, không nhập tồn."

    def add_arguments(self, parser):
        parser.add_argument("--master-file", required=True)
        parser.add_argument("--username", default="admin")
        batches = parser.add_mutually_exclusive_group()
        batches.add_argument("--collection", action="store_true", help="Chọn đợt danh mục 12 mã.")
        batches.add_argument(
            "--training-collection", action="store_true", help="Chọn đợt đối chiếu huấn luyện."
        )
        parser.add_argument(
            "--training-file", help="Đường dẫn training_observed_2022.csv cho đợt đối chiếu."
        )
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            config, digest = validate_bundle(
                options["master_file"],
                collection=options["collection"],
                training_collection=options["training_collection"],
                training_file=options["training_file"],
            )
            actor = User.objects.get(username=options["username"])
            result = import_catalog(actor, config, digest, apply=options["apply"])
        except (BusinessError, User.DoesNotExist, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False))
