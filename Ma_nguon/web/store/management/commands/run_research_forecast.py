import json

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError

from store.forecast.replenishment import month_parse
from store.forecast.research import generate_research
from store.models import User
from store.services.documents import BusinessError


class Command(BaseCommand):
    help = "Chạy lại bốn phương pháp cho kỳ nghiên cứu sau Validation set; không ghi tồn kho."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--dataset", type=int, required=True)
        parser.add_argument(
            "--target", required=True, help="YYYY-MM, thuộc các kỳ sau Validation set"
        )
        parser.add_argument("--experiment", type=int)

    def handle(self, *args, **options):
        try:
            result = generate_research(
                User.objects.get(username=options["username"]),
                options["dataset"],
                month_parse(options["target"]),
                options["experiment"],
            )
        except (BusinessError, ObjectDoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False))
