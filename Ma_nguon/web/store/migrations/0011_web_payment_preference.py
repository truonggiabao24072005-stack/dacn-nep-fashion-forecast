from importlib import import_module
from django.db import migrations
from django.db import models

_previous = import_module("store.migrations.0009_sql_web_and_link_guards").SQL
_snapshot = _previous[_previous.index("CREATE FUNCTION public.nep_web_snapshot_guard"): _previous.index("CREATE FUNCTION public.nep_web_check")]
_old = _snapshot.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
_new = _old.replace("NEW.note,NEW.total_amount", "NEW.note,NEW.payment_preference,NEW.total_amount").replace("OLD.note,OLD.total_amount", "OLD.note,OLD.payment_preference,OLD.total_amount")


class Migration(migrations.Migration):
    dependencies = [("store", "0010_database_order_lifecycle")]
    operations = [
        migrations.AddField(model_name="weborder", name="payment_preference", field=models.CharField("Phương thức khách chọn", max_length=12, choices=[("UNSPECIFIED", "Chưa chọn trong yêu cầu cũ"), ("CASH", "Tiền mặt tại quầy"), ("TRANSFER", "Chuyển khoản tại quầy")], default="UNSPECIFIED", db_default="UNSPECIFIED")),
        migrations.AddConstraint(model_name="weborder", constraint=models.CheckConstraint(condition=models.Q(payment_preference__in=["UNSPECIFIED", "CASH", "TRANSFER"]), name="web_payment_preference_valid")),
        migrations.RunSQL(_new, _old),
    ]
