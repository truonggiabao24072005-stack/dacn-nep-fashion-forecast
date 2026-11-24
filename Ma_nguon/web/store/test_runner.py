import json
import os
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.records = []
        self.started = {}

    def startTest(self, test):
        self.started[test.id()] = time.monotonic()
        super().startTest(test)

    def record(self, test, status, detail=""):
        self.records.append(
            {
                "test": test.id(),
                "status": status,
                "seconds": round(
                    time.monotonic() - self.started.get(test.id(), time.monotonic()), 4
                ),
                "detail": detail,
            }
        )

    def addSuccess(self, test):
        self.record(test, "passed")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.record(test, "failed", self._exc_info_to_string(err, test))
        super().addFailure(test, err)

    def addError(self, test, err):
        self.record(test, "error", self._exc_info_to_string(err, test))
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.record(test, "skipped", reason)
        super().addSkip(test, reason)


class EvidenceRunner(DiscoverRunner):
    def get_resultclass(self):
        return EvidenceResult

    def run_suite(self, suite, **kwargs):
        t = time.monotonic()
        result = super().run_suite(suite, **kwargs)
        directory = settings.BASE_DIR / ".runtime/evidence"
        directory.mkdir(parents=True, exist_ok=True)
        evidence_name = Path(os.environ.get("TEST_EVIDENCE_FILE", "tests_current.json")).name
        (directory / evidence_name).write_text(
            json.dumps(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "database": "PostgreSQL",
                    "count": result.testsRun,
                    "failures": len(result.failures),
                    "errors": len(result.errors),
                    "skipped": len(result.skipped),
                    "seconds": round(time.monotonic() - t, 3),
                    "tests": result.records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return result
