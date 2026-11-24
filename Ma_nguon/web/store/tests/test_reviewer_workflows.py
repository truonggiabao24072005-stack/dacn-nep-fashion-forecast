from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import TransactionTestCase
from django.utils import timezone

from store.models import StockBalance
from store.services.documents import BusinessError, confirm_document, create_document, set_line
from store.services.orders import accept_order, submit_order
from store.services.pickup import close_missed_pickup, held_quantities
from store.services.suppliers import (
    calculate_need,
    place_supplier_order,
    planned_incoming,
    receive_delivery,
)
from store.tests.test_business import fixture
from store.tests.test_shop import stock


class ReviewerWorkflows(TransactionTestCase):
    def setUp(self):
        self.admin, self.sales, self.warehouse, _, self.variant, _, self.supplier = fixture()
        stock(self.admin, self.variant, 8)

    def test_pickup_blocks_counter_sale_then_expires(self):
        request, _ = submit_order(
            "b" * 64,
            uuid4(),
            [(self.variant.pk, 7, str(self.variant.selling_price))],
            {"customer_name": "Khách thử", "phone": "0900000000"},
        )
        request = accept_order(self.sales, request.pk, request.version, hold_pickup=True)
        self.assertEqual(held_quantities([self.variant.pk]), {self.variant.pk: 7})
        counter = create_document(self.sales, "sale", {})
        counter = set_line(self.sales, "sale", counter.pk, counter.version, self.variant, 2)
        payment = {"method": "CASH", "cash_received": str(counter.total_amount)}
        with self.assertRaises(BusinessError):
            confirm_document(self.sales, "sale", counter.pk, counter.version, uuid4(), payment)
        with patch(
            "django.utils.timezone.now",
            return_value=request.pickup_expires_at + timedelta(seconds=1),
        ):
            self.assertFalse(held_quantities([self.variant.pk]))
            close_missed_pickup(self.sales, request.pk)
            confirm_document(self.sales, "sale", counter.pk, counter.version, uuid4(), payment)
        self.assertEqual(StockBalance.objects.get(pk=self.variant.pk).quantity, 6)

    def test_partial_supplier_receipt_and_net_reorder(self):
        today = timezone.localdate()
        order = place_supplier_order(
            self.warehouse,
            {
                "reference": "PO-01",
                "supplier": self.supplier,
                "variant": self.variant,
                "ordered_qty": 80,
                "expected_on": today + timedelta(days=3),
            },
        )
        self.assertEqual(planned_incoming(self.variant, today, today + timedelta(days=7)), 80)
        self.assertEqual(calculate_need(100, 30, 0, 0, 80)["quantity"], 20)
        self.assertEqual(calculate_need(100, 15, 0, 0, 80)["quantity"], 0)
        delivery = {
            "quantity": 30,
            "unit_cost": Decimal(50000),
            "delivery_reference": "PG-01",
            "request_key": uuid4(),
        }
        first = receive_delivery(self.warehouse, order.pk, **delivery)
        self.assertEqual(receive_delivery(self.warehouse, order.pk, **delivery).pk, first.pk)
        self.assertEqual(planned_incoming(self.variant, today, today + timedelta(days=7)), 50)
        with self.assertRaises(BusinessError):
            receive_delivery(
                self.warehouse,
                order.pk,
                **{**delivery, "quantity": 51, "delivery_reference": "PG-02"}
            )
        self.assertEqual(StockBalance.objects.get(pk=self.variant.pk).quantity, 38)

    def test_two_sizes_of_same_product_are_planned_separately(self):
        from django.urls import reverse

        from store.models import Category, Color, Product, Size, Variant

        category = Category.objects.create(code="GIAY", name="Giày")
        product = Product.objects.create(
            code="GIAY-THU",
            name="Giày kiểm thử",
            category=category,
            brand=self.variant.product.brand,
            unit="đôi",
        )
        first = Variant.objects.create(
            product=product,
            sku="GIAY-THU-40-DEN",
            selling_price=100000,
            size=Size.objects.create(code="40", name="40"),
            color=self.variant.color,
        )
        second = Variant.objects.create(
            product=product,
            sku="GIAY-THU-41-NAU",
            selling_price=100000,
            size=Size.objects.create(code="41", name="41"),
            color=Color.objects.create(code="NAU", name="Nâu"),
        )
        stock(self.admin, second, 30)
        order = place_supplier_order(
            self.warehouse,
            {
                "reference": "PO-SKU",
                "supplier": self.supplier,
                "variant": second,
                "ordered_qty": 80,
                "expected_on": timezone.localdate() + timedelta(days=3),
            },
        )
        self.client.force_login(self.warehouse)
        response = self.client.get(
            reverse("sku_plan"),
            {
                "variant": first.pk,
                "lead_days": 14,
                "safety": 10,
                "observed": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result"]["incoming"], 0)
        self.assertEqual(response.context["result"]["quantity"], 10)
        self.assertEqual(order.variant_id, second.pk)

    def test_full_return_preserves_sale_and_replenishes_correct_variant_once(self):
        from store.models import DocumentCorrection
        from store.services.documents import correct_document

        sale = create_document(self.sales, "sale", {})
        sale = set_line(self.sales, "sale", sale.pk, sale.version, self.variant, 2)
        confirm_document(
            self.sales,
            "sale",
            sale.pk,
            sale.version,
            uuid4(),
            {"method": "CASH", "cash_received": str(sale.total_amount)},
        )
        values = {
            "reason": "Khách trả hàng",
            "evidence": "Đã kiểm tra hàng và biên nhận hoàn tiền",
            "goods_ack": True,
            "financial_ack": True,
        }
        correct_document(self.admin, "sale", sale.pk, uuid4(), **values)
        with self.assertRaises(BusinessError):
            correct_document(self.admin, "sale", sale.pk, uuid4(), **values)
        self.assertEqual(StockBalance.objects.get(pk=self.variant.pk).quantity, 8)
        self.assertEqual(DocumentCorrection.objects.filter(original_sale=sale).count(), 1)
