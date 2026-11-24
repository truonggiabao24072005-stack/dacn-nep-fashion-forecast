from uuid import uuid4

from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from store.models import GatewayPayment, SalePayment, StockBalance, WebOrder
from store.services.documents import BusinessError, confirm_document
from store.services.orders import accept_order, submit_order
from store.services.vnpay import payment_url, signed_query, update_shipment
from store.tests.test_business import fixture
from store.tests.test_shop import count_stock, stock


@override_settings(
    VNPAY_TMN_CODE="TESTMERCHANT",
    VNPAY_SECRET="local-test-key",
    VNPAY_RETURN_URL="https://merchant.example/return",
    VNPAY_SANDBOX=True,
)
class GatewayTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.sales, _, _, self.variant, _, _ = fixture()
        stock(self.admin, self.variant, 8)
        order, _ = submit_order(
            "a" * 64,
            uuid4(),
            [(self.variant.pk, 2, str(self.variant.selling_price))],
            {
                "customer_name": "Khách thử",
                "phone": "0900000000",
                "delivery_address": "10 Đường Thử Nghiệm, Thành phố Hồ Chí Minh",
                "payment_method": "VNPAY",
            },
        )
        self.order = accept_order(self.sales, order.pk, order.version)
        url = payment_url(self.order, "127.0.0.1")
        self.assertTrue(url.startswith("https://sandbox.vnpayment.vn/"))
        self.payment = GatewayPayment.objects.get(order=self.order)

    def callback(self, **overrides):
        fields = {
            "vnp_TmnCode": "TESTMERCHANT",
            "vnp_TxnRef": self.payment.pk.hex,
            "vnp_Amount": str(self.payment.amount * 100),
            "vnp_TransactionNo": "10001",
            "vnp_ResponseCode": "00",
            "vnp_TransactionStatus": "00",
        }
        fields.update(overrides)
        query, signature = signed_query(fields)
        return (
            Client()
            .get(f"{reverse('vnpay_ipn')}?{query}&vnp_SecureHash={signature}")
            .json()["RspCode"]
        )

    def test_verified_payment_posts_stock_once_and_allows_shipment(self):
        self.assertEqual(StockBalance.objects.get(pk=self.variant.pk).quantity, 8)
        self.assertEqual(self.callback(vnp_Amount="1"), "04")
        self.assertEqual(self.callback(), "00")
        self.assertEqual(self.callback(), "02")
        self.assertEqual(StockBalance.objects.get(pk=self.variant.pk).quantity, 6)
        self.assertEqual(SalePayment.objects.get(sale=self.order.sale).method, "VNPAY")
        update_shipment(self.order.pk, "ship", "VAN-DON-01")
        update_shipment(self.order.pk, "deliver", "")
        self.assertEqual(WebOrder.objects.get(pk=self.order.pk).shipment_status, "DELIVERED")

    def test_cash_cannot_post_an_online_order_and_unowned_payment_is_hidden(self):
        with self.assertRaises(BusinessError):
            confirm_document(
                self.sales,
                "sale",
                self.order.sale_id,
                self.order.sale.version,
                uuid4(),
                {"method": "CASH", "cash_received": "9999999"},
            )
        result = Client().post(reverse("vnpay_pay", args=[self.order.pk]))
        self.assertEqual(result.status_code, 404)
        result = Client().get(reverse("vnpay_ipn"), {"vnp_TxnRef": self.payment.pk.hex})
        self.assertEqual(result.json()["RspCode"], "97")

    def test_payment_keeps_a_record_for_review_if_stock_changed(self):
        count_stock(self.admin, self.variant, 1)
        self.assertEqual(self.callback(), "00")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "REVIEW")
        self.assertFalse(SalePayment.objects.filter(sale=self.order.sale).exists())
        self.assertEqual(StockBalance.objects.get(pk=self.variant.pk).quantity, 1)
