import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from store.models import DatasetVersion, Product, Role, SaleOrder, StockPosting, SystemGuard, User


class StoreInitializationTests(TestCase):
    def initialize(self):
        with patch.dict(os.environ, {"STORE_ADMIN_PASSWORD": "CuaHang!2027xQ9"}):
            call_command("khoi_tao_cua_hang", stdout=StringIO())

    def test_initializes_real_store_without_stock_or_sales(self):
        self.initialize()
        admin = User.objects.get(username="admin")
        self.assertEqual(admin.role, Role.ADMIN)
        self.assertTrue(admin.check_password("CuaHang!2027xQ9"))
        self.assertEqual(SystemGuard.objects.get(pk=1).data_mode, "OPERATIONAL")
        for model in [Product, StockPosting, SaleOrder, DatasetVersion]:
            self.assertEqual(model.objects.count(), 0)
        self.client.force_login(admin)
        for url in [
            "/quan-tri/",
            "/danh-muc/products/tao/",
            "/chung-tu/receipt/tao/",
            "/chung-tu/sale/tao/",
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_retry_preserves_password_and_start_date(self):
        self.initialize()
        before = (
            User.objects.get(username="admin").password,
            SystemGuard.objects.get(pk=1).initialized_at,
        )
        self.initialize()
        self.assertEqual(
            before,
            (
                User.objects.get(username="admin").password,
                SystemGuard.objects.get(pk=1).initialized_at,
            ),
        )

    def test_existing_data_is_not_relabelled_or_overwritten(self):
        SystemGuard.objects.create(pk=1, data_mode="DEMO")
        with self.assertRaises(CommandError):
            self.initialize()
        self.assertEqual(SystemGuard.objects.get(pk=1).data_mode, "DEMO")
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password_rolls_back_initialization(self):
        with patch.dict(os.environ, {"STORE_ADMIN_PASSWORD": "1234567890"}):
            with self.assertRaises(CommandError):
                call_command("khoi_tao_cua_hang", stdout=StringIO())
        self.assertFalse(User.objects.exists())
        self.assertFalse(SystemGuard.objects.exists())
