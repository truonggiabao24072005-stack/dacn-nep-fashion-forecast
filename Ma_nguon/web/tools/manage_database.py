"""PostgreSQL administration for this project; never restore over its live database."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
import psycopg
from django.conf import settings
from psycopg import sql

CFG = settings.DATABASES["default"]
PRIVATE = BASE / ".runtime/backup"
EVIDENCE = BASE / ".runtime/evidence/sql_20261025"

RECONCILIATION_SQL = """-- Chi doc du lieu. Moi dong tra ve ten phep kiem tra va so ban ghi vi pham.
SELECT 'so_du_khop_so_kho' AS kiem_tra, count(*)::bigint AS so_loi
FROM store_stockbalance b
LEFT JOIN (SELECT variant_id,sum(delta) AS quantity FROM store_stockentry GROUP BY variant_id) e ON e.variant_id=b.variant_id
WHERE b.quantity<>coalesce(e.quantity,0)
UNION ALL
SELECT 'bien_the_thieu_so_du',count(*) FROM store_variant v LEFT JOIN store_stockbalance b ON b.variant_id=v.id WHERE b.variant_id IS NULL
UNION ALL
SELECT 'tong_don_ban',count(*) FROM store_saleorder s LEFT JOIN
  (SELECT sale_id,sum(quantity::numeric*unit_price) total FROM store_saleline GROUP BY sale_id) l ON l.sale_id=s.id
WHERE s.total_amount<>coalesce(l.total,0)
UNION ALL
SELECT 'tong_phieu_nhap',count(*) FROM store_goodsreceipt r LEFT JOIN
  (SELECT receipt_id,sum(quantity::numeric*unit_cost) total FROM store_receiptline GROUP BY receipt_id) l ON l.receipt_id=r.id
WHERE r.total_amount<>coalesce(l.total,0)
UNION ALL
SELECT 'thanh_toan_va_don_ban',count(*) FROM store_saleorder s LEFT JOIN store_salepayment p ON p.sale_id=s.id
WHERE (s.status='POSTED' AND (p.id IS NULL OR p.amount<>s.total_amount)) OR (s.status<>'POSTED' AND p.id IS NOT NULL)
UNION ALL
SELECT 'tong_yeu_cau_web',count(*) FROM store_weborder o LEFT JOIN
  (SELECT order_id,sum(quantity::numeric*unit_price) total FROM store_weborderline GROUP BY order_id) l ON l.order_id=o.id
WHERE o.total_amount<>coalesce(l.total,0)
UNION ALL
SELECT 'luong_thang_duong_am_rong',count(*) FROM store_monthlysales
WHERE positive_qty-negative_qty_abs<>net_qty OR positive_qty='NaN'::numeric OR negative_qty_abs='NaN'::numeric OR net_qty='NaN'::numeric
UNION ALL
SELECT 'du_bao_dung_bo_du_lieu',count(*) FROM store_forecastvalue v
JOIN store_forecastunit u ON u.id=v.forecast_unit_id JOIN store_forecastrun r ON r.id=v.run_id
JOIN store_modelresult m ON m.id=r.model_result_id JOIN store_experiment x ON x.id=m.experiment_id
WHERE u.dataset_version_id<>x.dataset_version_id
UNION ALL
SELECT 'du_bao_hop_le_co_gia_tri',count(*) FROM store_forecastvalue
WHERE result_status='VALID' AND (nonnegative_value IS NULL OR nonnegative_value<0 OR nonnegative_value>='100000000000000'::numeric)
UNION ALL
SELECT 'ky_du_bao_ke_tiep',count(*) FROM store_forecastrun
WHERE target_month<>(cutoff_month+interval '1 month')::date OR extract(day FROM cutoff_month)<>1
UNION ALL
SELECT 'but_toan_co_mot_chung_tu',count(*) FROM store_stockposting p
LEFT JOIN store_saleorder s ON s.stock_posting_id=p.id
LEFT JOIN store_goodsreceipt r ON r.stock_posting_id=p.id
LEFT JOIN store_stockadjustment a ON a.stock_posting_id=p.id
LEFT JOIN store_documentcorrection c ON c.stock_posting_id=p.id
WHERE (s.id IS NOT NULL)::int+(r.id IS NOT NULL)::int+(a.id IS NOT NULL)::int+(c.id IS NOT NULL)::int<>1;
"""

STRUCTURE_SQL = """BEGIN READ ONLY;
SELECT current_database() AS co_so_du_lieu,current_user AS tai_khoan,version() AS phien_ban;
SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user;
SELECT table_name,table_type FROM information_schema.tables WHERE table_schema='public' ORDER BY table_type,table_name;
SELECT table_name,column_name,data_type,is_nullable,numeric_precision,numeric_scale
FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position;
SELECT c.relname AS bang,x.conname AS rang_buoc,x.contype AS loai,pg_get_constraintdef(x.oid) AS dinh_nghia
FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' ORDER BY c.relname,x.conname;
SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname;
SELECT c.relname AS bang,t.tgname AS trigger,pg_get_triggerdef(t.oid) AS dinh_nghia
FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname;
COMMIT;
"""

MANAGEMENT_REPORT_SQL = """BEGIN READ ONLY;
SET LOCAL TIME ZONE 'Asia/Ho_Chi_Minh';
SELECT * FROM public.v_nep_ton_kho ORDER BY ma_san_pham,kich_co,mau;
SELECT * FROM public.v_nep_ton_kho
WHERE dang_ban AND nguong_canh_bao IS NOT NULL AND ton_hien_tai<=nguong_canh_bao ORDER BY ton_hien_tai,sku;
SELECT * FROM public.v_nep_don_ban ORDER BY don_ban_id DESC LIMIT 100;
SELECT ngay_ghi_so,sum(gia_tri) AS doanh_thu_sau_dieu_chinh,sum(so_luong) AS luong_sau_dieu_chinh
FROM public.v_nep_su_kien_doanh_thu GROUP BY ngay_ghi_so ORDER BY ngay_ghi_so DESC;
SELECT * FROM public.v_nep_so_kho ORDER BY dong_so_id DESC LIMIT 100;
SELECT * FROM public.v_nep_yeu_cau_web ORDER BY ma_yeu_cau DESC LIMIT 100;
SELECT loai_nguon,thang_chot,thang_du_bao,phuong_phap,trang_thai_ket_qua,count(*) AS so_ma
FROM public.v_nep_du_bao GROUP BY loai_nguon,thang_chot,thang_du_bao,phuong_phap,trang_thai_ket_qua
ORDER BY thang_du_bao DESC;
COMMIT;
"""


def connection_args(database=None):
    return dict(
        host=CFG["HOST"],
        port=CFG["PORT"],
        user=CFG["USER"],
        password=CFG["PASSWORD"],
        dbname=database or CFG["NAME"],
        connect_timeout=8,
    )


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pg(program, arguments, *, read_only=False, input_bytes=None):
    binary = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\18\bin")) / (
        program + ".exe" if os.name == "nt" else program
    )
    environment = {**os.environ, "PGPASSWORD": CFG["PASSWORD"], "PGCLIENTENCODING": "UTF8"}
    if read_only:
        environment["PGOPTIONS"] = (
            environment.get("PGOPTIONS", "") + " -c default_transaction_read_only=on"
        )
    result = subprocess.run(
        [
            str(binary),
            "--no-password",
            "-h",
            CFG["HOST"],
            "-p",
            str(CFG["PORT"]),
            "-U",
            CFG["USER"],
            *map(str, arguments),
        ],
        env=environment,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=180,
    )
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace")
        if CFG["PASSWORD"]:
            error = error.replace(CFG["PASSWORD"], "[REDACTED]")
        (BASE / ".runtime").mkdir(exist_ok=True)
        (BASE / ".runtime/sql_error.log").write_text(error, encoding="utf-8")
        raise RuntimeError(program + " failed; inspect .runtime/sql_error.log")
    return result.stdout


def structure(conn):
    queries = {
        "constraints": "SELECT c.relname,x.conname,x.contype,pg_get_constraintdef(x.oid) FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,x.conname",
        "indexes": "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname",
        "triggers": "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
        "views": "SELECT viewname,definition FROM pg_views WHERE schemaname='public' ORDER BY viewname",
        "functions": "SELECT p.proname,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' ORDER BY p.proname,p.oid",
    }
    return {name: conn.execute(query).fetchall() for name, query in queries.items()}


def canonical_constraint(definition):
    # PostgreSQL can deparse a varchar[] -> text[] cast as individual text
    # casts after restore. Normalize only these equivalent literal arrays;
    # keep every predicate, literal, column, bound and other cast unchanged.
    pattern = r"\(ARRAY\[((?:'[A-Z_]+'::character varying(?:, )?)+)\]\)::text\[\]"
    definition = re.sub(
        pattern,
        lambda match: "ARRAY[" + match.group(1).replace("::character varying", "::text") + "]",
        definition,
    )
    return re.sub(r"\('([A-Z_]+)'::character varying\)::text", r"'\1'::text", definition)


def canonical_structure(value):
    normalized = json.loads(json.dumps(value))
    for constraint in normalized["constraints"]:
        constraint[3] = canonical_constraint(constraint[3])
    return normalized


def controls(conn):
    conn.execute("SET LOCAL TIME ZONE 'UTC'")
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
    ).fetchall()
    output = {}
    for (name,) in tables:
        keys = conn.execute(
            "SELECT a.attname FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,position) JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum WHERE n.nspname='public' AND c.relname=%s AND i.indisprimary ORDER BY k.position",
            [name],
        ).fetchall()
        order = (
            sql.SQL(",").join(sql.Identifier("t", key[0]) for key in keys)
            if keys
            else sql.SQL("row_to_json(t)::text")
        )
        query = sql.SQL("SELECT row_to_json(t)::text FROM {} t ORDER BY {}").format(
            sql.Identifier("public", name), order
        )
        digest = hashlib.sha256()
        count = 0
        with conn.cursor(name="nep_control_" + uuid4().hex[:12]) as cursor:
            cursor.execute(query)
            while True:
                batch = cursor.fetchmany(2000)
                if not batch:
                    break
                for (record,) in batch:
                    digest.update(record.encode("utf-8"))
                    digest.update(b"\n")
                    count += 1
        output[name] = {"rows": count, "sha256": digest.hexdigest()}
    return output


def backup():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    dump = PRIVATE / (
        "doan_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "_"
        + uuid4().hex[:8]
        + ".dump"
    )
    with psycopg.connect(**connection_args()) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        run_pg(
            "pg_dump",
            ["-Fc", "--no-owner", "--no-acl", "--snapshot=" + snapshot, "-f", dump, CFG["NAME"]],
        )
        table_controls = controls(conn)
        schema = structure(conn)
    manifest = {
        "at": datetime.now(timezone.utc).isoformat(),
        "source_database": CFG["NAME"],
        "dump_file": dump.name,
        "dump_bytes": dump.stat().st_size,
        "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        "snapshot": snapshot,
        "tables": table_controls,
        "structure": schema,
        "cluster_roles_included": False,
        "object_privileges_included": False,
    }
    save(dump.with_suffix(".json"), manifest)
    print(
        json.dumps(
            {"backup": dump.name, "tables": len(table_controls), "snapshot_controls_saved": True}
        ),
        flush=True,
    )
    return dump, manifest


def safe_drop(database, marker):
    if database == CFG["NAME"] or not re.fullmatch(r"doan_sqlverify_[0-9a-f]{16}", database):
        raise ValueError("Refuse to remove a database outside the verifier namespace.")
    if not re.fullmatch(r"nep-sql-verifier:[0-9a-f]{32}", marker):
        raise ValueError("Missing verifier ownership marker.")
    with psycopg.connect(**connection_args("postgres"), autocommit=True) as conn:
        row = conn.execute(
            "SELECT pg_get_userbyid(datdba),shobj_description(oid,'pg_database'),current_user FROM pg_database WHERE datname=%s",
            [database],
        ).fetchone()
        if row is None:
            return
        if row[0] != row[2] or row[1] != marker:
            raise ValueError("Database owner or marker does not match; preserved for inspection.")
        conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def sequence_checks(conn):
    rows = conn.execute(
        "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND (is_identity='YES' OR column_default LIKE 'nextval(%%') ORDER BY table_name,column_name"
    ).fetchall()
    count = 0
    for table, column in rows:
        sequence = conn.execute(
            "SELECT pg_get_serial_sequence(%s,%s)", ["public." + table, column]
        ).fetchone()[0]
        if not sequence:
            continue
        schema, name = sequence.split(".", 1)
        last, called = conn.execute(
            sql.SQL("SELECT last_value,is_called FROM {}").format(sql.Identifier(schema, name))
        ).fetchone()
        maximum = conn.execute(
            sql.SQL("SELECT max({}) FROM {}").format(
                sql.Identifier(column), sql.Identifier("public", table)
            )
        ).fetchone()[0]
        if maximum is not None and (last < maximum or (last == maximum and not called)):
            raise RuntimeError("Restored sequence would reuse an existing identifier.")
        count += 1
    return count


def verify(dump=None, keep=False):
    if dump is None:
        dump, manifest = backup()
    else:
        dump = Path(dump).resolve()
        manifest = json.loads(dump.with_suffix(".json").read_text(encoding="utf-8"))
        if hashlib.sha256(dump.read_bytes()).hexdigest() != manifest["dump_sha256"]:
            raise ValueError("Backup checksum does not match its control file.")
    database = "doan_sqlverify_" + uuid4().hex[:16]
    marker = "nep-sql-verifier:" + uuid4().hex
    # Creation is exclusive: an existing database is never reused or overwritten.
    with psycopg.connect(**connection_args("postgres"), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        conn.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(database), sql.Literal(marker)
            )
        )
    save(
        PRIVATE / (database + ".json"),
        {"database": database, "marker": marker, "source_database": CFG["NAME"]},
    )
    try:
        run_pg("pg_restore", ["--exit-on-error", "--no-owner", "--no-acl", "-d", database, dump])
        with psycopg.connect(**connection_args(database)) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            restored_controls = controls(conn)
            restored_schema = structure(conn)
            if restored_controls != manifest["tables"]:
                raise RuntimeError("Restored table values differ from the backup snapshot.")
            if canonical_structure(restored_schema) != canonical_structure(manifest["structure"]):
                raise RuntimeError("Restored schema differs from the backup snapshot.")
            violations = dict(conn.execute(RECONCILIATION_SQL).fetchall())
            if any(violations.values()):
                raise RuntimeError("Restored business reconciliation failed.")
            sequences = sequence_checks(conn)
        if not keep:
            safe_drop(database, marker)
        result = {
            "at": datetime.now(timezone.utc).isoformat(),
            "passed": True,
            "tables_compared": len(restored_controls),
            "rows_compared": sum(row["rows"] for row in restored_controls.values()),
            "every_table_value_hashed": True,
            "schema_compared": True,
            "constraint_cast_normalization": "varchar literal arrays to text arrays only",
            "sequences_checked": sequences,
            "reconciliation": violations,
            "dump_file": dump.name,
            "dump_bytes": dump.stat().st_size,
            "dump_sha256": manifest["dump_sha256"],
            "verification_database": database,
            "verification_database_removed": not keep,
            "source_database_overwritten": False,
            "cluster_roles_restored": False,
            "privileges_restored": False,
        }
        save(EVIDENCE / "backup_restore.json", result)
        print(json.dumps(result), flush=True)
        return result
    except Exception as error:
        save(
            EVIDENCE / "backup_restore_failure.json",
            {
                "passed": False,
                "error": type(error).__name__,
                "verification_database_preserved": database,
                "cleanup_marker_file": database + ".json",
                "source_database_overwritten": False,
            },
        )
        raise


def export_schema():
    target = BASE / ".runtime/schema_export.sql"
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_suffix(".pending.sql")
    data = run_pg("pg_dump", ["--schema-only", "--no-owner", "--no-acl", CFG["NAME"]])
    pending.write_bytes(data)
    pending.replace(target)
    print(
        json.dumps(
            {
                "schema": str(target.relative_to(BASE)),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "data_included": False,
            }
        )
    )


REPORTS = {
    "cau-truc": STRUCTURE_SQL,
    "kiem-tra": RECONCILIATION_SQL,
    "bao-cao": MANAGEMENT_REPORT_SQL,
}


def report(name):
    sql_bytes = REPORTS[name].encode("utf-8")
    output = run_pg(
        "psql",
        ["-X", "--set", "ON_ERROR_STOP=1", "-d", CFG["NAME"]],
        read_only=True,
        input_bytes=sql_bytes,
    )
    print(output.decode("utf-8"), end="")
    save(
        EVIDENCE / ("query_" + name + ".json"),
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "passed": True,
            "read_only": True,
            "report": name,
            "sql_sha256": hashlib.sha256(sql_bytes).hexdigest(),
            "output_sha256": hashlib.sha256(output).hexdigest(),
        },
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup")
    sub.add_parser("export-schema")
    sub.add_parser("status")
    query = sub.add_parser("query")
    query.add_argument("--report", choices=REPORTS, required=True)
    restore = sub.add_parser("verify")
    restore.add_argument("--dump", type=Path)
    restore.add_argument("--keep", action="store_true")
    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("--database", required=True)
    cleanup.add_argument("--marker", required=True)
    args = parser.parse_args(argv)
    if args.command == "backup":
        backup()
    elif args.command == "verify":
        verify(args.dump, args.keep)
    elif args.command == "export-schema":
        export_schema()
    elif args.command == "query":
        report(args.report)
    elif args.command == "cleanup":
        safe_drop(args.database, args.marker)
        print("Verifier database removed or already absent.")
    else:
        from audit_sql import main as status

        previous = sys.argv
        try:
            sys.argv = [sys.argv[0], "--stage", "status"]
            status()
        finally:
            sys.argv = previous


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, psycopg.Error, subprocess.SubprocessError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1)
