from django.core.management.base import BaseCommand, CommandError

from store.forecast.experiments import install_experiment
from store.models import User
from store.services.documents import BusinessError


class Command(BaseCommand):
    help = "Nạp riêng bản nghiên cứu cải tiến có dấu kiểm tra và bộ Metrics đã đối chiếu."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", required=True, type=int)
        parser.add_argument("--username", default="admin")

    def handle(self, *args, **options):
        try:
            exp, created = install_experiment(
                User.objects.get(username=options["username"]), options["dataset"]
            )
        except (BusinessError, User.DoesNotExist, OSError, KeyError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Experiment {exp.pk}; created={created}")
