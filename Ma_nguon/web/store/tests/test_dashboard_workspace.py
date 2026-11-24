from django.test import TestCase
from django.urls import reverse

from store.models import Role, User
from store.services.documents import cancel_draft, create_document
from store.tests.test_business import fixture


class DashboardWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.sales, cls.warehouse, _, _, _, cls.supplier = fixture()
        cls.other_sales = User.objects.create_user("sales2", role=Role.SALES)
        cls.other_warehouse = User.objects.create_user("warehouse2", role=Role.WAREHOUSE)
        cls.mine = create_document(cls.sales, "sale", {"customer": None})
        cls.other = create_document(cls.other_sales, "sale", {"customer": None})
        cls.receipt = create_document(cls.warehouse, "receipt", {"supplier": cls.supplier})
        create_document(cls.other_warehouse, "receipt", {"supplier": cls.supplier})
        cancelled = create_document(cls.sales, "sale", {"customer": None})
        cancel_draft(cls.sales, "sale", cancelled.pk, cancelled.version, "Đóng hồ sơ kiểm thử")

    def test_admin_sees_store_counts_and_cancelled_records_remain_searchable(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sale_drafts"], 2)
        self.assertEqual(response.context["receipt_drafts"], 2)
        self.assertEqual(set(response.context["recent"]), {self.mine, self.other})
        self.assertContains(
            self.client.get(reverse("documents", args=["sale"]) + "?status=CANCELLED"),
            "Đã hủy nháp",
        )

    def test_sales_counts_and_links_follow_document_ownership(self):
        self.client.force_login(self.sales)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["sale_drafts"], 1)
        self.assertIsNone(response.context["receipt_drafts"])
        self.assertEqual(list(response.context["recent"]), [self.mine])
        self.assertNotContains(response, reverse("document_new", args=["receipt"]))
        self.assertNotContains(response, reverse("report"))

    def test_warehouse_counts_and_links_exclude_sales_and_web_requests(self):
        self.client.force_login(self.warehouse)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["receipt_drafts"], 1)
        self.assertIsNone(response.context["pending_web"])
        self.assertIsNone(response.context["sale_drafts"])
        self.assertEqual(response.context["recent_kind"], "receipt")
        self.assertEqual(list(response.context["recent"]), [self.receipt])
        self.assertNotContains(response, reverse("web_orders"))
        self.assertNotContains(response, reverse("document_new", args=["sale"]))
