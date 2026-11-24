from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from store.models import (
    AuditEvent,
    GoodsReceipt,
    SaleOrder,
    SalePayment,
    StockBalance,
    StockEntry,
    SystemGuard,
    WebOrder,
)
from store.services.catalog_import import import_catalog
from store.tests import test_source_catalog as source_fixture


class SampleCatalogueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        source_fixture.SourceCatalogTests.setUpTestData.__func__(cls)
        import_catalog(cls.admin, cls.config, "b" * 64, apply=True)
        SystemGuard.objects.filter(pk=1).update(data_mode="DEMO")

    def run_sample(self, apply=True):
        return call_command(
            "tao_du_lieu_mau", username=self.admin.username, apply=apply, stdout=StringIO()
        )

    def test_dry_run_creates_no_documents_or_stock(self):
        before = StockEntry.objects.count()
        self.run_sample(False)
        self.assertEqual(StockEntry.objects.count(), before)
        self.assertFalse(GoodsReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="SEED_CURRENT_CATALOGUE").exists())

    def test_posts_through_services_and_retry_does_not_replenish(self):
        self.run_sample()
        self.assertEqual(GoodsReceipt.objects.filter(status="POSTED").count(), 1)
        self.assertEqual(SaleOrder.objects.filter(status="POSTED").count(), 4)
        self.assertEqual(SalePayment.objects.count(), 4)
        self.assertEqual(WebOrder.objects.count(), 2)
        self.assertEqual(WebOrder.objects.filter(status="PENDING").count(), 1)
        before = list(
            StockBalance.objects.order_by("pk").values("variant_id", "quantity", "version")
        )
        count = StockEntry.objects.count()
        self.run_sample()
        self.assertEqual(
            before,
            list(StockBalance.objects.order_by("pk").values("variant_id", "quantity", "version")),
        )
        self.assertEqual(StockEntry.objects.count(), count)

    def test_operational_database_rejects_sample_without_writes(self):
        SystemGuard.objects.filter(pk=1).update(data_mode="OPERATIONAL")
        with self.assertRaises(CommandError):
            self.run_sample()
        self.assertFalse(GoodsReceipt.objects.exists())
