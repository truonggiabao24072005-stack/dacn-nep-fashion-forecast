from django.test import TestCase
from django.urls import reverse

from store.models import Product, Variant
from store.tests.test_business import fixture


class ProductEditorTests(TestCase):
    def test_create_product_then_add_variant_to_the_selected_product(self):
        admin, _, _, existing, sample, _, _ = fixture()
        self.client.force_login(admin)

        create_product = reverse("catalog_new", args=["products"])
        self.assertContains(self.client.get(create_product), "Lưu và thêm biến thể")
        response = self.client.post(
            create_product,
            {
                "code": "GIAY-MOI",
                "name": "Giày mới",
                "category": existing.category_id,
                "brand": existing.brand_id,
                "unit": "đôi",
                "is_active": "on",
                "version": 1,
                "next_step": "variant",
            },
        )
        product = Product.objects.get(code="GIAY-MOI")
        create_variant = reverse("catalog_new", args=["variants"], query={"product": product.pk})
        self.assertRedirects(response, create_variant)
        self.assertTrue(self.client.get(create_variant).context["form"].fields["product"].disabled)

        response = self.client.post(
            create_variant,
            {
                "sku": "GIAY-MOI-01",
                "product": existing.pk,
                "size": sample.size_id,
                "color": sample.color_id,
                "selling_price": 120000,
                "is_active": "on",
                "version": 1,
                "next_step": "another_variant",
            },
        )
        self.assertRedirects(response, create_variant)
        variant = Variant.objects.get(sku="GIAY-MOI-01")
        self.assertEqual(variant.product, product)
        self.assertEqual(variant.balance.quantity, 0)
