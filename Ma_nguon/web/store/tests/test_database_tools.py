from importlib.util import module_from_spec, spec_from_file_location
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase


class DatabaseToolSafetyTests(SimpleTestCase):
    def module(self):
        spec = spec_from_file_location(
            "nep_sql_tools", settings.BASE_DIR / "tools/manage_database.py"
        )
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_SQL17_cleanup_rejects_live_and_unmarked_database_names_before_connecting(self):
        module = self.module()
        with patch.object(module.psycopg, "connect") as connect:
            for database, marker in [
                (module.CFG["NAME"], "nep-sql-verifier:" + "a" * 32),
                ("unrelated_database", "nep-sql-verifier:" + "a" * 32),
                ("doan_sqlverify_" + "a" * 16, "wrong-marker"),
            ]:
                with self.subTest(database=database), self.assertRaises(ValueError):
                    module.safe_drop(database, marker)
            connect.assert_not_called()

    def test_SQL18_cleanup_checks_owner_and_marker_before_drop(self):
        module = self.module()
        with patch.object(module.psycopg, "connect") as connect:
            conn = connect.return_value.__enter__.return_value
            conn.execute.return_value.fetchone.return_value = (
                "another_owner",
                "nep-sql-verifier:" + "a" * 32,
                "current_owner",
            )
            with self.assertRaises(ValueError):
                module.safe_drop("doan_sqlverify_" + "a" * 16, "nep-sql-verifier:" + "a" * 32)
            self.assertEqual(conn.execute.call_count, 1)

    def test_SQL21_equivalent_postgresql_array_casts_compare_equal(self):
        module = self.module()
        source = "CHECK (status = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[]))"
        restored = "CHECK (status = ANY (ARRAY[('DRAFT'::character varying)::text, ('CANCELLED'::character varying)::text]))"
        self.assertEqual(module.canonical_constraint(source), module.canonical_constraint(restored))
        changed = restored.replace("CANCELLED", "POSTED")
        self.assertNotEqual(
            module.canonical_constraint(source), module.canonical_constraint(changed)
        )
