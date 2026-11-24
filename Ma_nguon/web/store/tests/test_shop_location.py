from unittest.mock import patch
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from store.models import AuditEvent, ShopLocation, WebOrder
from store.services.orders import submit_order
from store.tests.test_business import fixture
from store.tests.test_shop import stock


class ShopLocationTests(TestCase):
    address = "12 Đường Kiểm Thử, phường Kiểm Thử, Thành phố Hồ Chí Minh"

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, _, _, cls.variant, _, _ = fixture()
        stock(cls.admin, cls.variant)

    def test_only_admin_can_publish_and_clear_location(self):
        route = reverse("manage_shop_location")
        self.assertEqual(self.client.get(route).status_code, 302)
        self.client.force_login(self.sales)
        self.assertEqual(self.client.post(route, {"address": self.address}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertRedirects(
            self.client.post(route, {"address": self.address, "is_example": "on"}), route
        )
        self.assertTrue(AuditEvent.objects.filter(action="UPDATE_SHOP_LOCATION").exists())
        for name in ("shop_home", "shop_about"):
            page = self.client.get(reverse(name))
            self.assertContains(page, self.address)
            self.assertContains(page, "Địa chỉ minh họa cho đồ án")
            self.assertContains(page, "https://www.google.com/maps/dir/?api=1&amp;destination=")
        self.assertRedirects(self.client.post(route, {"address": "", "is_example": "on"}), route)
        self.assertNotContains(self.client.get(reverse("shop_home")), self.address)

    def test_pickup_order_keeps_original_address_after_store_address_changes(self):
        location = ShopLocation.objects.create(address=self.address, is_example=True)
        shopper = Client()
        shopper.post(
            reverse("shop_cart_action"),
            {"action": "add", "variant_id": self.variant.pk, "quantity": 1},
        )
        route = reverse("shop_checkout")
        page = shopper.get(route)
        self.assertContains(page, "Địa chỉ nhận tại cửa hàng")
        form = page.context["form"]
        result = shopper.post(
            route,
            {
                "request_key": form.initial["request_key"],
                "quote": form.initial["quote"],
                "customer_name": "Khách kiểm thử",
                "phone": "0900000000",
                "payment_method": "CASH",
            },
        )
        order = WebOrder.objects.get()
        self.assertRedirects(result, reverse("shop_order", args=[order.pk]))
        self.assertEqual(order.pickup_address, self.address)
        self.assertTrue(order.pickup_address_is_example)
        location.address = "42 Đường Mới, Thành phố Hồ Chí Minh"
        location.save()
        page = shopper.get(reverse("shop_order", args=[order.pk]))
        self.assertEqual(page.context["order_pickup_location"]["address"], self.address)
        self.assertContains(page, self.address)
        self.assertContains(page, location.address)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WebOrder.objects.filter(pk=order.pk).update(pickup_address=location.address)

    @patch("store.services.orders.gateway_available", return_value=True)
    def test_delivery_does_not_capture_pickup_address(self, _gateway):
        ShopLocation.objects.create(address=self.address, is_example=True)
        order, _ = submit_order(
            "a" * 64,
            uuid4(),
            [(self.variant.pk, 1, str(self.variant.selling_price))],
            {
                "customer_name": "Khách kiểm thử",
                "phone": "0900000000",
                "payment_method": "VNPAY",
                "delivery_address": "Địa chỉ giao hàng kiểm thử số 10",
            },
        )
        self.assertFalse(order.pickup_address)
        self.assertFalse(order.pickup_address_is_example)
        self.assertTrue(order.delivery_address)
