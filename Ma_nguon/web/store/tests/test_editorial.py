from django.test import TestCase
from django.urls import reverse

from store.models import ShopPost
from store.tests.test_business import fixture


class EditorialTests(TestCase):
    def test_draft_publish_and_hide(self):
        admin, sales, *_ = fixture()
        editor = reverse("shop_new_post")
        data = {"title": "Tin thử", "summary": "Thông tin mới", "body": "<script>alert(1)</script>"}

        self.client.force_login(sales)
        self.assertEqual(self.client.post(editor, data).status_code, 403)
        self.client.force_login(admin)
        self.assertRedirects(self.client.post(editor, data), reverse("shop_manage_posts"))
        post = ShopPost.objects.get(title=data["title"])
        article = reverse("shop_article", args=[post.pk])
        self.assertEqual(self.client.get(article).status_code, 404)

        edit = reverse("shop_edit_post", args=[post.pk])
        self.assertRedirects(
            self.client.post(edit, {**data, "publish": "on"}), reverse("shop_manage_posts")
        )
        self.client.logout()
        self.assertContains(self.client.get(reverse("shop_news")), "Tin thử")
        self.assertContains(self.client.get(article), "&lt;script&gt;")
        self.assertNotContains(self.client.get(article), "<script>alert(1)</script>")
        self.assertContains(self.client.get(reverse("shop_about")), "Về Nếp")

        self.client.force_login(admin)
        self.client.post(edit, data)
        self.assertEqual(self.client.get(article).status_code, 404)
