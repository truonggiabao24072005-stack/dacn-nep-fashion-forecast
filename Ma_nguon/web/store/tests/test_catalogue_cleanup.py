from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from store.models import Product, Variant
from store.services.presentation import PHOTO_CREDITS, SOURCE_PRODUCTS, presentation
from store.tests.test_business import fixture
from store.tests.test_shop import stock


class Options(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_filter = False
        self.values = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.in_filter = attrs.get("name") == "active"
        if tag == "option" and self.in_filter:
            self.values.append(attrs.get("value"))

    def handle_endtag(self, tag):
        if tag == "select":
            self.in_filter = False


class CatalogueScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, _, _, cls.product, cls.v, cls.v2, _ = fixture()
        old = Product.objects.create(
            code="RETIRED",
            name="Hàng ngừng bán",
            category=cls.product.category,
            brand=cls.product.brand,
            unit=cls.product.unit,
        )
        cls.old = Variant.objects.create(
            product=old, sku="RETIRED-SKU", size=cls.v.size, color=cls.v.color, selling_price=100000
        )
        stock(cls.admin, cls.v, 5)
        stock(cls.admin, cls.old, 20)
        Product.objects.filter(pk=old.pk).update(is_active=False)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_dashboard_splits_sellable_stock_and_flags_zero_without_threshold(self):
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.context["stock"], 5)
        self.assertEqual(r.context["unavailable_stock"], 20)
        self.assertEqual(r.context["out_of_stock_count"], 1)
        self.assertEqual(r.context["unconfigured_count"], 1)
        self.assertContains(r, "Tồn đang mở bán")

    def test_catalogue_has_all_three_valid_filter_options(self):
        r = self.client.get(reverse("catalog", args=["products"]))
        parser = Options()
        parser.feed(r.content.decode())
        self.assertEqual(parser.values, ["", "1", "0"])
        self.assertEqual(r.context["active"], "1")

    def test_product_catalogue_defaults_to_active_and_can_open_history(self):
        url = reverse("catalog", args=["products"])
        self.assertEqual(self.client.get(url).context["page"].paginator.count, 1)
        self.assertEqual(self.client.get(url, {"active": ""}).context["page"].paginator.count, 2)
        self.assertEqual(self.client.get(url, {"active": "0"}).context["page"].paginator.count, 1)

    def test_variant_catalogue_uses_parent_state(self):
        url = reverse("catalog", args=["variants"])
        self.assertEqual(self.client.get(url).context["page"].paginator.count, 2)
        r = self.client.get(url, {"active": "0"})
        self.assertEqual([v.pk for v in r.context["page"]], [self.old.pk])
        self.assertContains(r, "Chưa đủ điều kiện bán")

    def test_inventory_default_matches_web_and_preserves_all_stock_option(self):
        url = reverse("inventory")
        self.assertEqual(
            {b.variant_id for b in self.client.get(url).context["page"]}, {self.v.pk, self.v2.pk}
        )
        self.assertEqual(self.client.get(url, {"mode": "all"}).context["page"].paginator.count, 3)
        self.assertEqual(
            self.client.get(url, {"mode": "unavailable"}).context["page"].paginator.count, 1
        )

    def test_out_filter_includes_zero_with_no_threshold_and_excludes_retired(self):
        r = self.client.get(reverse("inventory"), {"mode": "out"})
        self.assertEqual([b.variant_id for b in r.context["page"]], [self.v2.pk])
        self.assertContains(r, "Hết hàng")


class CurrentAssetsTests(SimpleTestCase):
    def test_only_current_photos_remain_and_each_source_has_three_views(self):
        self.assertEqual(len(PHOTO_CREDITS), 72)
        expected = {settings.BASE_DIR / row["file"] for row in PHOTO_CREDITS}
        self.assertEqual(set((settings.BASE_DIR / "static/shop/images").rglob("*.jpg")), expected)
        for code in SOURCE_PRODUCTS:
            self.assertEqual(len(presentation(type("Product", (), {"code": code})())["gallery"]), 3)

    def test_superseded_catalogue_and_commands_are_removed(self):
        for relative in [
            "store/shop_photos.json",
            "store/demo_catalog_extra.json",
            "store/management/commands/seed_demo.py",
            "store/management/commands/expand_demo_catalog.py",
        ]:
            self.assertFalse((settings.BASE_DIR / relative).exists())
