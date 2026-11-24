"""Start the local demo once; keep the PID of the healthy process only."""

import subprocess
import time
import urllib.request
from pathlib import Path

ADDRESS = "http://127.0.0.1:8891/"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def database_ready(base):
    probe = """import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.db import connections
connection = connections['default']
connection.settings_dict.setdefault('OPTIONS', {})['connect_timeout'] = 5
with connection.cursor() as cursor:
    cursor.execute('SELECT 1')
    assert cursor.fetchone() == (1,)
connection.close()
"""
    try:
        result = subprocess.run(
            [str(base / ".venv/Scripts/python.exe"), "-c", probe],
            cwd=base,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            creationflags=HIDDEN,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def web_ready():
    try:
        with urllib.request.urlopen(ADDRESS + "dang-nhap/", timeout=2) as response:
            html = response.read(65536).decode("utf-8")
            return response.status == 200 and "<title>Đăng nhập · Nếp</title>" in html
    except (OSError, UnicodeError):
        return False


def start_server(base=None):
    base = Path(base) if base is not None else Path(__file__).resolve().parents[1]
    runtime = base / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    if not database_ready(base):
        raise SystemExit(
            "Cannot connect to PostgreSQL. Check the PostgreSQL service and DB_* settings in .env (see CSDL/HUONG_DAN_CHAY_POSTGRESQL.txt)."
        )
    if web_ready():
        print("Web is already running at " + ADDRESS)
        return
    with (runtime / "web.log").open("ab") as log:
        process = subprocess.Popen(
            [
                str(base / ".venv/Scripts/python.exe"),
                "-u",
                str(base / "manage.py"),
                "runserver",
                "127.0.0.1:8891",
                "--noreload",
            ],
            cwd=base,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=HIDDEN,
        )
    for _ in range(40):
        if process.poll() is not None:
            raise SystemExit("Web worker stopped before becoming ready. Inspect .runtime/web.log")
        if web_ready() and process.poll() is None:
            (runtime / "web.pid").write_text(str(process.pid), encoding="ascii")
            print("Web running at " + ADDRESS)
            return
        time.sleep(0.25)
    if process.poll() is None:
        process.terminate()
    raise SystemExit("Web did not become ready. Inspect .runtime/web.log")


if __name__ == "__main__":
    start_server()
