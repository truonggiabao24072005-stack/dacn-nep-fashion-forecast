from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from store.models import *
from store.services.documents import create_document, set_line
from store.tests import test_business as business_fixture


class SQLIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.kho, cls.product, cls.v, cls.v2, cls.supplier = (
            business_fixture.fixture()
        )

    opening = business_fixture.BusinessTests.opening
    sale = business_fixture.BusinessTests.sale
    post_sale = business_fixture.BusinessTests.post_sale
    forecast_value = business_fixture.BusinessTests.forecast_value

    def setUp(self):
        self.opening()
        self.posted = self.post_sale(self.sale(2))

    def rejected(self, query, params=()):
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(query, params)
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_SQL01_total_cannot_be_negative(self):
        draft = self.sale(1)
        self.rejected("UPDATE store_saleorder SET total_amount=-1 WHERE id=%s", [draft.pk])

    def test_SQL02_nan_is_not_a_valid_selling_price(self):
        self.rejected(
            "UPDATE store_variant SET selling_price='NaN'::numeric WHERE id=%s", [self.v.pk]
        )

    def test_SQL03_monthly_net_must_equal_positive_minus_negative(self):
        value = self.forecast_value()
        self.rejected(
            "INSERT INTO store_monthlysales(forecast_unit_id,month,positive_qty,negative_qty_abs,net_qty,target_qty,observation_status,source_row_count) VALUES(%s,'2026-01-01',3,1,999,3,'OBSERVED',2)",
            [value.forecast_unit_id],
        )

    def test_SQL04_forecast_cannot_point_to_another_dataset(self):
        first = self.forecast_value()
        second = self.forecast_value()
        self.rejected(
            "UPDATE store_forecastvalue SET forecast_unit_id=%s WHERE id=%s",
            [second.forecast_unit_id, first.pk],
        )

    def test_SQL05_balance_cannot_be_changed_without_ledger_entries(self):
        self.rejected(
            "UPDATE store_stockbalance SET quantity=quantity+1 WHERE variant_id=%s", [self.v.pk]
        )

    def test_SQL06_recorded_stock_entries_cannot_be_edited(self):
        row = StockEntry.objects.filter(variant=self.v).first()
        self.rejected("UPDATE store_stockentry SET delta=delta+1 WHERE id=%s", [row.pk])

    def test_SQL07_audit_history_cannot_be_deleted(self):
        row = AuditEvent.objects.first()
        self.rejected("DELETE FROM store_auditevent WHERE id=%s", [row.pk])

    def test_SQL08_posted_document_cannot_be_edited(self):
        self.rejected(
            "UPDATE store_saleorder SET customer_name_snapshot='Changed by SQL' WHERE id=%s",
            [self.posted.pk],
        )

    def test_SQL09_posted_lines_cannot_be_edited(self):
        self.rejected(
            "UPDATE store_saleline SET quantity=quantity+1 WHERE sale_id=%s", [self.posted.pk]
        )

    def test_SQL10_recorded_payment_cannot_be_changed(self):
        self.rejected(
            "UPDATE store_salepayment SET reference='Changed by SQL' WHERE sale_id=%s",
            [self.posted.pk],
        )

    def test_SQL11_draft_total_and_lines_must_reconcile_at_commit(self):
        draft = self.sale(1)
        self.rejected(
            "UPDATE store_saleorder SET total_amount=total_amount+1 WHERE id=%s", [draft.pk]
        )

    def test_SQL12_stock_posting_requires_a_business_document(self):
        self.rejected(
            "INSERT INTO store_stockposting(kind,business_key,posted_by_id,posted_at) VALUES('SALE','orphan-sql',%s,now())",
            [self.admin.pk],
        )

    def test_SQL13_valid_forecast_requires_a_numeric_value(self):
        value = self.forecast_value()
        self.rejected(
            "UPDATE store_forecastvalue SET nonnegative_value=NULL WHERE id=%s", [value.pk]
        )

    def test_SQL14_variant_cannot_lose_its_balance_row(self):
        self.rejected("DELETE FROM store_stockbalance WHERE variant_id=%s", [self.v.pk])

    def test_SQL15_foreign_key_and_unique_sku_are_enforced(self):
        self.rejected(
            "UPDATE store_variant SET product_id=9223372036854775807 WHERE id=%s", [self.v.pk]
        )
        self.rejected("UPDATE store_variant SET sku=%s WHERE id=%s", [self.v.sku, self.v2.pk])

    def test_SQL16_current_catalog_price_can_change_without_rewriting_history(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE store_variant SET selling_price=110000 WHERE id=%s", [self.v.pk])
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self.assertEqual(self.posted.lines.get().unit_price, Decimal("100000"))

    def test_SQL19_opening_stock_cannot_be_posted_twice(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            draft = create_document(
                self.admin,
                "adjustment",
                {"kind": "OPENING", "reason": "SQL duplicate opening test"},
            )
            draft = set_line(self.admin, "adjustment", draft.pk, draft.version, self.v, 8)
            posting = StockPosting.objects.create(
                kind="OPENING",
                business_key="StockAdjustment:" + str(draft.pk),
                posted_by=self.admin,
            )
            StockAdjustment.objects.filter(pk=draft.pk).update(
                status="POSTED",
                posted_by=self.admin,
                posted_at=posting.posted_at,
                stock_posting=posting,
            )
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_SQL20_used_sku_identity_and_product_unit_are_preserved(self):
        self.rejected("UPDATE store_variant SET sku='REWRITTEN-SKU' WHERE id=%s", [self.v.pk])
        self.rejected(
            "UPDATE store_product SET unit='different-unit' WHERE id=%s", [self.product.pk]
        )
