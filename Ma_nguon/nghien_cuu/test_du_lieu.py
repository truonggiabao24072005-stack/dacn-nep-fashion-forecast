import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from du_lieu import monthly_matrix, read_monthly


class MonthlyDataTests(unittest.TestCase):
    def read(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monthly.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["product_id", "unit_alias", "month", "positive_qty", "negative_qty_abs", "net_qty"])
                writer.writerows(rows)
            return read_monthly(path)

    def test_unobserved_month_stays_unknown_and_observed_zero_is_preserved(self):
        rows = self.read([["1", "MH1", "2023-01", 0, 0, 0], ["1", "MH1", "2023-03", 5, 2, 3]])
        _, months, matrix, _ = monthly_matrix(rows)
        self.assertEqual(len(months), 3)
        self.assertEqual(matrix[0, 0], 0)
        self.assertTrue(np.isnan(matrix[0, 1]))
        self.assertEqual(matrix[0, 2], 5)

    def test_duplicate_product_month_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "trùng"):
            self.read([["1", "MH1", "2023-01", 1, 0, 1]] * 2)

    def test_invalid_quantities_and_inconsistent_net_are_rejected(self):
        for qty, negative, net in [("nan", 0, 0), (-1, 0, -1), (2, 1, 2), (2, -1, 3)]:
            with self.subTest(qty=qty, negative=negative, net=net), self.assertRaises(ValueError):
                self.read([["1", "MH1", "2023-01", qty, negative, net]])

    def test_inconsistent_alias_is_rejected(self):
        rows = self.read([["1", "MH1", "2023-01", 1, 0, 1], ["1", "MH2", "2023-02", 1, 0, 1]])
        with self.assertRaises(ValueError):
            monthly_matrix(rows)

    def test_training_import_does_not_initialize_django(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c", "import sys; import train; assert 'django' not in sys.modules"],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_output_inside_source_directory_is_rejected(self):
        import contextlib
        import io
        from train import main

        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(io.StringIO()):
            source = Path(directory) / "Du_lieu"
            output = source / "Nguon" / "new_run"
            with self.assertRaises(SystemExit) as error:
                main(["--data-dir", str(source), "--output-dir", str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
