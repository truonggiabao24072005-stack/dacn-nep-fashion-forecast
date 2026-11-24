"""Project audit. HTTP probes run inside rolled-back transactions; no sales are posted."""

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from datetime import timezone as datetime_timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.conf import settings
from django.core.checks import run_checks
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import F, Sum, Value
from django.db.models.functions import Coalesce
from django.test import Client, override_settings

from store.models import *


def snapshot():
    models = [
        User,
        CustomerProfile,
        Product,
        Variant,
        Customer,
        Supplier,
        SaleOrder,
        SaleLine,
        SalePayment,
        GoodsReceipt,
        ReceiptLine,
        StockAdjustment,
        AdjustmentLine,
        DocumentCorrection,
        StockPosting,
        StockEntry,
        AuditEvent,
        WebOrder,
        WebOrderLine,
        DatasetVersion,
        ForecastUnit,
        MonthlySales,
        ForecastValue,
    ]
    rows = list(
        Variant.objects.order_by("pk").values(
            "pk",
            "sku",
            "product_id",
            "product__name",
            "product__unit",
            "size__code",
            "color__code",
            "selling_price",
            "balance__quantity",
            "balance__version",
            "version",
            "is_active",
        )
    )
    return {
        "counts": {m.__name__: m.objects.count() for m in models},
        "variant_sha256": hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=str).encode()
        ).hexdigest(),
    }


def backup():
    cfg = settings.DATABASES["default"]
    target = BASE / ".runtime/backup"
    target.mkdir(exist_ok=True)
    dump = target / (
        "before_audit_" + datetime.now(datetime_timezone.utc).strftime("%Y%m%dT%H%M%S") + ".dump"
    )
    subprocess.run(
        [
            r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe",
            "-h",
            cfg["HOST"],
            "-p",
            str(cfg["PORT"]),
            "-U",
            cfg["USER"],
            "-Fc",
            "--no-owner",
            "--no-acl",
            "-f",
            str(dump),
            cfg["NAME"],
        ],
        env={**os.environ, "PGPASSWORD": cfg["PASSWORD"]},
        check=True,
        capture_output=True,
    )
    return {
        "file": dump.name,
        "bytes": dump.stat().st_size,
        "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
    }


def probe(client, name, method, url, data=None, expected=(200, 302, 400, 404, 405)):
    # Each request has its own savepoint, including requests that raise a database error.
    with transaction.atomic():
        response = getattr(client, method)(url, data or {})
        row = {
            "name": name,
            "method": method.upper(),
            "url": url,
            "status": response.status_code,
            "expected": list(expected),
            "passed": response.status_code in expected,
        }
        if getattr(response, "exc_info", None):
            row["exception"] = response.exc_info[0].__name__
        transaction.set_rollback(True)
    return row


def http_checks():
    routes = []

    def route(url, roles):
        routes.append((url, set(roles)))

    staff = STAFF_ROLES
    for url in ["/quan-tri/", "/ton-kho/", "/huong-dan/"]:
        route(url, staff)
    for kind in ["products", "variants", "categories", "brands", "sizes", "colors"]:
        route("/danh-muc/" + kind + "/", staff)
        route("/danh-muc/" + kind + "/tao/", [Role.ADMIN])
    route("/danh-muc/customers/", [Role.ADMIN, Role.SALES])
    route("/danh-muc/suppliers/", [Role.ADMIN, Role.WAREHOUSE])
    for kind, roles in [
        ("sale", [Role.ADMIN, Role.SALES]),
        ("receipt", [Role.ADMIN, Role.WAREHOUSE]),
        ("adjustment", [Role.ADMIN]),
        ("correction", [Role.ADMIN]),
    ]:
        route("/chung-tu/" + kind + "/", roles)
        if kind != "correction":
            route("/chung-tu/" + kind + "/tao/", roles)
    for url in ["/nhan-vien/", "/nhan-vien/tao/", "/bao-cao/", "/nhat-ky/", "/doi-mat-khau/"]:
        route(url, [Role.ADMIN] if url != "/doi-mat-khau/" else staff)
    for url in ["/du-bao/"]:
        route(url, [Role.ADMIN, Role.WAREHOUSE])
    route("/quan-tri/don-tren-web/", [Role.ADMIN, Role.SALES])
    v = Variant.objects.order_by("pk").first()
    fv = ForecastValue.objects.order_by("pk").first()
    if v:
        route(f"/ton-kho/{v.pk}/", [Role.ADMIN, Role.WAREHOUSE])
    if fv:
        route(f"/du-bao/{fv.pk}/", [Role.ADMIN, Role.WAREHOUSE])
    matrix = []
    boundaries = []
    logger = logging.getLogger("django.request")
    old_level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        with transaction.atomic(), override_settings(
            DEBUG=False, ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False
        ):
            users = {"anonymous": None}
            for role in staff:
                users[role] = User.objects.filter(role=role, is_active=True).first()
            users[Role.CUSTOMER] = User.objects.create_user(
                "audit_" + uuid4().hex, full_name="Khách kiểm tra tạm", role=Role.CUSTOMER
            )
            clients = {}
            for role, user in users.items():
                if role != "anonymous" and user is None:
                    continue
                client = Client(raise_request_exception=False)
                if user:
                    client.force_login(user)
                clients[role] = client
                for url, allowed in routes:
                    expected = (
                        (302,) if role == "anonymous" else (200,) if role in allowed else (403,)
                    )
                    row = probe(client, "access", "get", url, expected=expected)
                    row["role"] = str(role)
                    matrix.append(row)
                for url in [
                    "/",
                    "/san-pham/",
                    "/nguon-anh/",
                    "/gio-hang/",
                    "/don-hang-cua-toi/",
                    "/tai-khoan/dang-nhap/",
                    "/tai-khoan/dang-ky/",
                ]:
                    row = probe(client, "public", "get", url, expected=(200, 302))
                    row["role"] = str(role)
                    matrix.append(row)
            admin = clients.get(Role.ADMIN)
            guest = clients["anonymous"]
            if admin:
                for value in ["²", "9" * 5000]:
                    boundaries.append(
                        probe(
                            admin, "forecast_dataset_invalid", "get", "/du-bao/", {"dataset": value}
                        )
                    )
                boundaries.append(
                    probe(
                        admin,
                        "report_max_date",
                        "get",
                        "/bao-cao/",
                        {"start": "9999-12-31", "end": "9999-12-31", "group": "day"},
                    )
                )
                for day in ["0001-01-01", "9999-12-30"]:
                    boundaries.append(
                        probe(
                            admin,
                            "report_representable_extreme",
                            "get",
                            "/bao-cao/",
                            {"start": day, "end": day, "group": "day"},
                            expected=(200,),
                        )
                    )
                boundaries.append(
                    probe(
                        admin,
                        "employee_login_self_next",
                        "get",
                        "/dang-nhap/",
                        {"next": "/dang-nhap/"},
                    )
                )
                for url in ["/ton-kho/", "/danh-muc/products/", "/du-bao/"]:
                    boundaries.append(probe(admin, "search_null", "get", url, {"q": "x\x00y"}))
                sale = SaleOrder.objects.order_by("pk").first()
                if sale:
                    boundaries.append(
                        probe(
                            admin,
                            "remove_invalid_variant",
                            "post",
                            f"/chung-tu/sale/{sale.pk}/thao-tac/",
                            {"action": "remove", "variant": "abc", "version": "1"},
                        )
                    )
            variant = (
                Variant.objects.filter(is_active=True, balance__quantity__gt=0)
                .order_by("pk")
                .first()
            )
            boundaries.append(probe(guest, "search_null", "get", "/san-pham/", {"q": "x\x00y"}))
            boundaries.append(
                probe(
                    guest,
                    "cart_long_variant",
                    "post",
                    "/gio-hang/cap-nhat/",
                    {"variant_id": "9" * 5000, "quantity": "1"},
                )
            )
            if variant:
                boundaries.append(
                    probe(
                        guest,
                        "cart_long_quantity",
                        "post",
                        "/gio-hang/cap-nhat/",
                        {"variant_id": str(variant.pk), "quantity": "9" * 5000},
                    )
                )
            for url in [
                "/.env",
                "/.runtime/pgdata/PG_VERSION",
                "/static/../.env",
                "/khong-ton-tai/",
            ]:
                boundaries.append(
                    probe(guest, "private_or_missing_path", "get", url, expected=(400, 403, 404))
                )
            transaction.set_rollback(True)
    finally:
        logger.setLevel(old_level)
    return matrix, boundaries


def integrity():
    mismatches = (
        StockBalance.objects.annotate(
            ledger=Coalesce(Sum("variant__stock_entries__delta"), Value(0))
        )
        .exclude(quantity=F("ledger"))
        .count()
    )
    monthly_bad = MonthlySales.objects.exclude(
        net_qty=F("positive_qty") - F("negative_qty_abs")
    ).count()
    forecast_bad = ForecastValue.objects.exclude(
        forecast_unit__dataset_version=F("run__model_result__experiment__dataset_version")
    ).count()
    totals = []
    for model in [SaleOrder, GoodsReceipt]:
        for doc in model.objects.all():
            total = sum((line.line_total for line in doc.lines.all()), 0)
            if total != doc.total_amount:
                totals.append({"kind": model.__name__, "pk": doc.pk})
    payment_bad = SalePayment.objects.exclude(amount=F("sale__total_amount")).count()
    executor = MigrationExecutor(connection)
    return {
        "stock_mismatches": mismatches,
        "monthly_flow_mismatches": monthly_bad,
        "forecast_scope_mismatches": forecast_bad,
        "document_total_mismatches": totals,
        "payment_total_mismatches": payment_bad,
        "pending_migrations": len(executor.migration_plan(executor.loader.graph.leaf_nodes())),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", default="review_" + datetime.now(datetime_timezone.utc).strftime("%Y%m%dT%H%M%S")
    )
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()
    directory = BASE / ".runtime/evidence/audit_20261025"
    directory.mkdir(parents=True, exist_ok=True)
    before = snapshot()
    saved = backup() if args.backup else None
    matrix, boundaries = http_checks()
    after = snapshot()
    assert before == after, "Audit changed persistent business data."
    local_checks = [
        {"id": message.id, "message": str(message.msg)}
        for message in run_checks(include_deployment_checks=True)
    ]
    with override_settings(
        DEBUG=False,
        SECURE_HSTS_SECONDS=31536000,
        SECURE_SSL_REDIRECT=True,
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
    ):
        https_checks = [
            {"id": message.id, "message": str(message.msg)}
            for message in run_checks(include_deployment_checks=True)
        ]
    result = {
        "at": datetime.now(datetime_timezone.utc).isoformat(),
        "stage": args.stage,
        "backup": saved,
        "snapshot": after,
        "business_data_unchanged": True,
        "integrity": integrity(),
        "access_matrix": matrix,
        "boundary_probes": boundaries,
    }
    result["deployment_checks"] = {
        "local_http": local_checks,
        "simulated_https_configuration": https_checks,
        "local_settings_changed": False,
    }
    (directory / (args.stage + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failed = [r for r in matrix + boundaries if not r["passed"]]
    print(
        json.dumps(
            {
                "stage": args.stage,
                "access_cases": len(matrix),
                "boundary_cases": len(boundaries),
                "failed": failed,
                "integrity": result["integrity"],
                "backup": saved,
            },
            ensure_ascii=True,
        )
    )
    if failed or any(result["integrity"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
