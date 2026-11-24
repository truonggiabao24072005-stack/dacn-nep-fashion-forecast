import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from store.forecast.replenishment import suggestion_reasons
from store.models import (
    AuditEvent,
    DatasetVersion,
    Experiment,
    ExternalSkuMap,
    ForecastRun,
    ForecastUnit,
    ForecastValue,
    ModelResult,
    Product,
    SourceFile,
    StockEntry,
    Variant,
)
from store.pricing import rounded_selling_price
from store.services.catalog_import import import_catalog, source_rows, validate_bundle
from store.services.documents import BusinessError
from store.services.presentation import SOURCE_PRODUCTS
from store.tests.test_business import fixture
from store.tests.test_shop import stock


class SourceCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, _, cls.old, cls.v, _, _ = fixture()
        cls.old.code = "SP001"
        cls.old.save()
        stock(cls.admin, cls.v, 8)
        cls.config = json.loads(
            (Path(__file__).parents[1] / "data/products.json").read_text(encoding="utf-8")
        )
        cls.ds = DatasetVersion.objects.create(
            code=cls.config["dataset_code"],
            source_type="RESEARCH",
            manifest_hash="a" * 64,
            coverage_start=date(2022, 1, 1),
            coverage_end=date(2023, 7, 1),
            status="VALIDATED",
            created_by=cls.admin,
        )
        SourceFile.objects.create(
            dataset_version=cls.ds,
            relative_name=cls.config["source_file"],
            sha256=cls.config["source_sha256"],
            row_count=94867,
            schema_version="1",
            validation_status="VALID",
        )
        for p in cls.config["products"]:
            u = ForecastUnit.objects.create(
                dataset_version=cls.ds,
                external_key=p["source_product_id"],
                label=p["code"],
                granularity="SKU",
                unit="đơn vị nguồn",
                scope_key="SOURCE_SNAPSHOT",
            )
            ExternalSkuMap.objects.create(forecast_unit=u, external_product_id=u.external_key)

    def run_import(self, **kwargs):
        return import_catalog(self.admin, self.config, "b" * 64, apply=True, **kwargs)

    def test_source_01_dry_run_does_not_write_catalogue_or_mapping(self):
        before = AuditEvent.objects.count()
        result = import_catalog(self.admin, self.config, "b" * 64)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), before)
        self.assertFalse(ForecastUnit.objects.filter(internal_product__isnull=False).exists())

    def test_source_02_import_preserves_old_stock_and_creates_no_posting(self):
        before = StockEntry.objects.count()
        self.run_import()
        self.old.refresh_from_db()
        self.v.balance.refresh_from_db()
        self.assertFalse(self.old.is_active)
        self.assertEqual(self.v.balance.quantity, 8)
        self.assertEqual(StockEntry.objects.count(), before)
        self.assertEqual(Variant.objects.filter(product__code__in=SOURCE_PRODUCTS).count(), 24)
        self.assertFalse(
            Variant.objects.filter(
                product__code__in=SOURCE_PRODUCTS, balance__quantity__gt=0
            ).exists()
        )
        for p in self.config["products"]:
            v = Variant.objects.get(sku=p["sku"])
            self.assertEqual(
                (v.product.category.code, v.size.code, v.color.code),
                (p["category_code"], p["size_code"], p["color_code"]),
            )
            self.assertEqual(v.selling_price, rounded_selling_price(p["listing_price"]))
            u = ForecastUnit.objects.get(external_key=p["source_product_id"])
            self.assertEqual(u.internal_product_id, v.product_id)
            self.assertEqual(u.granularity, "SKU")
            self.assertEqual(u.external_skus.get().internal_variant_id, v.pk)

    def test_source_03_repeat_preserves_subsequently_edited_price(self):
        self.run_import()
        v = Variant.objects.get(sku=self.config["products"][0]["sku"])
        v.selling_price += 1
        v.save()
        count = AuditEvent.objects.count()
        self.assertEqual(self.run_import()["status"], "unchanged")
        v.refresh_from_db()
        self.assertEqual(v.selling_price, rounded_selling_price(self.config["products"][0]["listing_price"]) + 1)
        self.assertEqual(AuditEvent.objects.count(), count)
        with self.assertRaises(BusinessError):
            import_catalog(self.admin, self.config, "c" * 64, apply=True)

    def test_source_04_bad_alias_and_existing_mapping_are_rejected(self):
        u = ForecastUnit.objects.first()
        u.label = "WRONG"
        u.save()
        with self.assertRaises(BusinessError):
            self.run_import()
        self.assertEqual(Product.objects.count(), 1)
        self.old.refresh_from_db()
        self.assertTrue(self.old.is_active)

    def test_source_05_sales_staff_cannot_import(self):
        with self.assertRaises(PermissionDenied):
            import_catalog(self.sales, self.config, "b" * 64, apply=True)

    def test_source_06_source_mapping_does_not_enable_research_replenishment(self):
        self.run_import()
        u = ForecastUnit.objects.first()
        ex = Experiment.objects.create(dataset_version=self.ds, status="SUCCEEDED")
        model = ModelResult.objects.create(
            experiment=ex, method="naive", selected_on_validation=True
        )
        run = ForecastRun.objects.create(
            model_result=model,
            cutoff_month=date(2023, 7, 1),
            target_month=date(2023, 8, 1),
            scope_key="SOURCE_SNAPSHOT",
            status="SUCCEEDED",
        )
        value = ForecastValue.objects.create(
            run=run,
            forecast_unit=u,
            raw_value=Decimal("3"),
            nonnegative_value=Decimal("3"),
            result_status="VALID",
        )
        reasons = suggestion_reasons(value)
        self.assertIn("Nguồn hiện tại chưa đủ điều kiện ghép với tồn cửa hàng.", reasons)
        self.assertIn("Chưa xác minh ánh xạ ở cấp sản phẩm.", reasons)
        self.ds.refresh_from_db()
        self.assertEqual(self.ds.source_type, "RESEARCH")

    def test_source_07_filters_and_three_gallery_images_match_active_catalogue(self):
        self.run_import()
        response = self.client.get(reverse("shop_catalogue"))
        self.assertEqual(response.context["page"].paginator.count, 24)
        self.assertEqual({s.code for s in response.context["sizes"]}, {"37", "40", "41"})
        self.assertNotIn("TRANG", {c.code for c in response.context["colors"]})
        p = Product.objects.get(code=self.config["products"][0]["code"])
        response = self.client.get(reverse("shop_product", args=[p.pk]))
        self.assertEqual(len(response.context["item"]["gallery"]), 3)
        self.assertContains(response, "chưa xác nhận là ảnh của mã nguồn")
        self.assertEqual(
            self.client.get(reverse("shop_product", args=[self.old.pk])).status_code, 404
        )


class SourceWorkbookTests(SimpleTestCase):
    def test_source_08_workbook_preserves_string_ids_and_numeric_sizes(self):
        xml = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
        <row r="1"><c r="A1" t="inlineStr"><is><t>product_id</t></is></c><c r="B1" t="inlineStr"><is><t>size</t></is></c></row>
        <row r="2"><c r="A2" t="inlineStr"><is><t>000001DEN40</t></is></c><c r="B2"><v>40</v></c></row>
        </sheetData></worksheet>"""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.xlsx"
            with ZipFile(path, "w") as book:
                book.writestr("xl/worksheets/sheet1.xml", xml)
            rows = source_rows(path, {"000001DEN40"})
            self.assertEqual(rows["000001DEN40"]["size"], Decimal("40"))
            with self.assertRaisesMessage(BusinessError, "sai SHA-256"):
                validate_bundle(path)
