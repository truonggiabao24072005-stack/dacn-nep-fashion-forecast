"""Check current Python sources and locally served catalogue photographs."""

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main():
    failures = []
    skip = {".venv", ".runtime", "__pycache__", ".git", "staticfiles"}
    sources = [p for p in BASE.rglob("*.py") if not skip.intersection(p.relative_to(BASE).parts)]
    for p in sources:
        try:
            ast.parse(p.read_text(encoding="utf-8-sig"), filename=str(p))
        except (SyntaxError, UnicodeError) as exc:
            failures.append({"file": str(p.relative_to(BASE)), "error": type(exc).__name__})
    sys.path.insert(0, str(BASE))
    from store.services.presentation import PHOTO_CREDITS, SOURCE_PRODUCTS, presentation

    expected = set()
    for photo in PHOTO_CREDITS:
        p = BASE / photo["file"]
        expected.add(p)
        if not p.is_file():
            failures.append({"file": photo["file"], "error": "missing"})
            continue
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != photo["sha256"] or len(data) != photo["bytes"]:
            failures.append({"file": photo["file"], "error": "checksum"})
        if not data.startswith(b"\xff\xd8\xff"):
            failures.append({"file": photo["file"], "error": "not-jpeg"})
        served = BASE / "staticfiles" / photo["static_path"]
        if (
            not served.is_file()
            or hashlib.sha256(served.read_bytes()).hexdigest() != photo["sha256"]
        ):
            failures.append({"file": photo["static_path"], "error": "served-copy-mismatch"})
    extra = set((BASE / "static/shop/images").rglob("*.jpg")) - expected
    for p in extra:
        failures.append({"file": str(p.relative_to(BASE)), "error": "unreferenced-photo"})
    for code in SOURCE_PRODUCTS:
        if len(presentation(type("Product", (), {"code": code})())["gallery"]) != 3:
            failures.append({"product": code, "error": "gallery-size"})
    refs = set()
    for p in (BASE / "templates").rglob("*.html"):
        refs.update(re.findall(r"{%\s*static\s+['\"]([^'\"]+)['\"]", p.read_text(encoding="utf-8")))
    for ref in refs:
        if not (BASE / "static" / ref).is_file():
            failures.append({"file": ref, "error": "template-static-missing"})
    result = {
        "passed": not failures,
        "python_files_parsed": len(sources),
        "photo_files_verified": len(PHOTO_CREDITS),
        "products_with_three_photos": len(SOURCE_PRODUCTS),
        "literal_static_refs": len(refs),
        "orphan_photos": len(extra),
        "failures": failures,
    }
    target = BASE / ".runtime/evidence/audit_files_current.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
