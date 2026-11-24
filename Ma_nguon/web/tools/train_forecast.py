"""Chạy công cụ huấn luyện từ thư mục website."""

import sys
from pathlib import Path

research = Path(__file__).resolve().parents[2] / "nghien_cuu"
sys.path.insert(0, str(research))
from train import main


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise SystemExit(f"Không hoàn tất huấn luyện: {exc}") from exc
