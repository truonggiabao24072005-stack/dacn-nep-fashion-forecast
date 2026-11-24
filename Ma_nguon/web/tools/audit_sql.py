"""Inspect the actual PostgreSQL catalogue and run read-only reconciliation SQL."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from audit_project import snapshot
from django.db import connection, transaction


def inspect_database():
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SELECT current_database(),current_user,current_setting('server_version')")
        database, user, version = cursor.fetchone()
        cursor.execute(
            "SELECT table_name,table_type FROM information_schema.tables WHERE table_schema='public' ORDER BY table_type,table_name"
        )
        relations = [{"name": name, "type": kind} for name, kind in cursor.fetchall()]
        cursor.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        )
        role = dict(
            zip(
                ["superuser", "createdb", "createrole", "replication", "bypassrls"],
                cursor.fetchone(),
            )
        )
        cursor.execute(
            "SELECT table_name,column_name,data_type,udt_name,is_nullable,character_maximum_length,numeric_precision,numeric_scale,numeric_precision_radix FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position"
        )
        columns = [
            dict(zip([column.name for column in cursor.description], row))
            for row in cursor.fetchall()
        ]
        cursor.execute(
            "SELECT c.relname AS table_name,x.conname,x.contype,x.convalidated,pg_get_constraintdef(x.oid) definition FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,x.conname"
        )
        constraints = [
            dict(zip([column.name for column in cursor.description], row))
            for row in cursor.fetchall()
        ]
        cursor.execute(
            "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname"
        )
        indexes = [
            dict(zip([column.name for column in cursor.description], row))
            for row in cursor.fetchall()
        ]
        cursor.execute(
            "SELECT c.relname AS table_name,t.tgname,pg_get_triggerdef(t.oid) definition FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname"
        )
        triggers = [
            dict(zip([column.name for column in cursor.description], row))
            for row in cursor.fetchall()
        ]
        cursor.execute((BASE / "sql/02_kiem_tra_toan_ven.sql").read_text(encoding="utf-8"))
        reconciliation = {name: count for name, count in cursor.fetchall()}
    return {
        "database": database,
        "user": user,
        "postgresql": version,
        "role_flags": role,
        "relations": relations,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "triggers": triggers,
        "reconciliation": reconciliation,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", default="review_" + datetime.now(timezone.utc).strftime("%H%M%S")
    )
    parser.add_argument("--dictionary", action="store_true")
    args = parser.parse_args()
    if Path(args.stage).name != args.stage:
        raise SystemExit("Stage must be a file name.")
    before = snapshot()
    result = inspect_database()
    after = snapshot()
    result.update(
        at=datetime.now(timezone.utc).isoformat(),
        business_data_unchanged=before == after,
        passed=before == after and not any(result["reconciliation"].values()),
    )
    output = BASE / ".runtime/evidence/sql_20261025"
    output.mkdir(exist_ok=True, parents=True)
    (output / (args.stage + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.dictionary:
        lines = [
            "# Từ điển dữ liệu PostgreSQL",
            "",
            "Sinh từ information_schema và pg_catalog của cơ sở dữ liệu đang cài. Không chứa giá trị bản ghi hoặc mật khẩu. Xem README.md để quản lý bằng SQL.",
            "",
        ]
        for relation in result["relations"]:
            name = relation["name"]
            lines.extend(
                [
                    "## " + name + " — " + relation["type"],
                    "",
                    "| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |",
                    "|---|---|---|---|",
                ]
            )
            for column in result["columns"]:
                if column["table_name"] == name:
                    size = column["character_maximum_length"] or ""
                    if column["numeric_precision"] is not None:
                        size = (
                            (str(column["numeric_precision"]) + " bit")
                            if column["numeric_precision_radix"] == 2
                            else "precision="
                            + str(column["numeric_precision"])
                            + ", scale="
                            + str(column["numeric_scale"])
                        )
                    lines.append(
                        "| "
                        + column["column_name"]
                        + " | "
                        + column["udt_name"]
                        + " | "
                        + column["is_nullable"]
                        + " | "
                        + str(size)
                        + " |"
                    )
            lines.extend(["", "Ràng buộc:", ""])
            for constraint in result["constraints"]:
                if constraint["table_name"] == name and constraint["contype"] != "n":
                    lines.append(
                        "- `"
                        + constraint["conname"]
                        + "`: `"
                        + constraint["definition"].replace("`", "")
                        + "`"
                    )
            lines.append("")
        (BASE / "sql/TU_DIEN_DU_LIEU.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "stage": args.stage,
                "passed": result["passed"],
                "tables": sum(r["type"] == "BASE TABLE" for r in result["relations"]),
                "views": sum(r["type"] == "VIEW" for r in result["relations"]),
                "constraints": len(result["constraints"]),
                "indexes": len(result["indexes"]),
                "custom_triggers": len(result["triggers"]),
                "reconciliation": result["reconciliation"],
                "role_flags": result["role_flags"],
            }
        )
    )
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
