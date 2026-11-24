"""Tạo giao dịch mẫu cho danh mục giày dép hiện hành, không sửa nghiên cứu."""

import json
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from store.forecast.replenishment import sellable_variants
from store.models import AuditEvent, Role, SystemGuard, User
from store.services.catalog import save_catalog, set_safety_stock
from store.services.documents import audit, authorize, confirm_document, create_document, set_line
from store.services.orders import accept_order, submit_order
from store.services.presentation import SOURCE_PRODUCTS

BATCH = "SAMPLE_FOOTWEAR_20261108"
NOTE = "Dữ liệu mẫu phục vụ đồ án; không phải giao dịch kinh doanh hoặc dữ liệu huấn luyện."


class Command(BaseCommand):
    help = "Tạo một đợt giao dịch mẫu cho 24 mã hiện hành, chỉ trên CSDL DEMO; chạy lại không nhập thêm."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument(
            "--apply", action="store_true", help="Ghi dữ liệu mẫu qua các dịch vụ nghiệp vụ."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        guard = SystemGuard.objects.select_for_update().filter(pk=1).first()
        if not guard or guard.data_mode != "DEMO":
            raise CommandError(
                "Chỉ tạo dữ liệu mẫu trên cơ sở dữ liệu DEMO; không trộn vào cửa hàng vận hành."
            )
        actor = User.objects.filter(username=options["username"]).first()
        if not actor:
            raise CommandError("Không tìm thấy quản trị viên.")
        actor = authorize(actor, [Role.ADMIN], lock=True)
        previous = AuditEvent.objects.filter(
            action="SEED_CURRENT_CATALOGUE", changed_fields__batch=BATCH
        ).first()
        if previous:
            self.stdout.write("Đã có đợt dữ liệu mẫu này; không nhập thêm hoặc đặt lại số tồn.")
            return
        variants = list(
            sellable_variants()
            .filter(product__code__in=SOURCE_PRODUCTS)
            .select_related("product", "size", "color", "balance")
            .order_by("product__code")
        )
        if len(variants) != 24 or len({v.product_id for v in variants}) != 24:
            raise CommandError("Cần đủ 24 sản phẩm nguồn và một biến thể đang bán cho mỗi mã.")
        if any(v.balance.quantity for v in variants):
            raise CommandError(
                "Danh mục đã có tồn; không tự trộn thêm dữ liệu mẫu vào số dư hiện có."
            )
        if not options["apply"]:
            self.stdout.write(
                "Dự kiến: 1 phiếu nhập đã xác nhận, 4 đơn bán hoàn tất, 2 yêu cầu web, 1 đơn bán nháp và 1 phiếu nhập nháp. Chưa ghi dữ liệu; dùng --apply để tạo."
            )
            return
        supplier = save_catalog(
            actor,
            "suppliers",
            {
                "code": "NCC-MAU",
                "name": "Nhà cung cấp mẫu giày dép",
                "phone": "",
                "address": "Hồ sơ mẫu phục vụ đồ án",
                "is_active": True,
            },
        )
        customers = [
            save_catalog(
                actor,
                "customers",
                {
                    "code": f"KH-MAU-{i:02}",
                    "name": f"Khách hàng mẫu {i:02}",
                    "phone": "",
                    "note": NOTE,
                    "is_active": True,
                },
            )
            for i in range(1, 4)
        ]
        receipt = create_document(
            actor, "receipt", {"supplier": supplier, "delivery_reference": BATCH, "note": NOTE}
        )
        for i, variant in enumerate(variants):
            values = {
                field: getattr(variant, field)
                for field in ["sku", "product", "size", "color", "selling_price", "is_active"]
            }
            values["low_stock_threshold"] = 4
            variant = save_catalog(actor, "variants", values, variant.pk, variant.version)
            set_safety_stock(actor, variant.product_id, 5)
            quantity = 3 if i in [22, 23] else 16 + 4 * (i % 5)
            cost = max(1, int(variant.selling_price * Decimal("0.65")))
            receipt = set_line(
                actor, "receipt", receipt.pk, receipt.version, variant, quantity, cost
            )
        receipt = confirm_document(actor, "receipt", receipt.pk, receipt.version, uuid4())
        posted = []
        for i, lines in enumerate([[(0, 2), (1, 1)], [(2, 1), (3, 2)], [(5, 1)], [(22, 3)]]):
            sale = create_document(actor, "sale", {"customer": customers[i % 3], "note": NOTE})
            for index, quantity in lines:
                sale = set_line(actor, "sale", sale.pk, sale.version, variants[index], quantity)
            payment = (
                {"method": "CASH", "cash_received": str(sale.total_amount)}
                if i % 2 == 0
                else {
                    "method": "TRANSFER",
                    "transfer_ack": True,
                    "reference": f"MAU-CHUYEN-KHOAN-{i+1:02}",
                }
            )
            sale = confirm_document(actor, "sale", sale.pk, sale.version, uuid4(), payment=payment)
            posted.append(sale.pk)
        draft = create_document(actor, "sale", {"customer": customers[0], "note": NOTE})
        draft = set_line(actor, "sale", draft.pk, draft.version, variants[6], 1)
        receipt_draft = create_document(
            actor,
            "receipt",
            {"supplier": supplier, "delivery_reference": BATCH + "-NHAP", "note": NOTE},
        )
        receipt_draft = set_line(
            actor,
            "receipt",
            receipt_draft.pk,
            receipt_draft.version,
            variants[23],
            8,
            max(1, int(variants[23].selling_price * Decimal("0.65"))),
        )
        web = []
        for i in range(2):
            variant = variants[8 + i]
            order, _ = submit_order(
                sha256((BATCH + str(i)).encode()).hexdigest(),
                uuid4(),
                [(variant.pk, 1, str(variant.selling_price))],
                {
                    "customer_name": f"Khách đặt web mẫu {i+1}",
                    "phone": "0900000000",
                    "note": NOTE + " Số điện thoại thử; không dùng để liên hệ.",
                },
            )
            if i == 1:
                order = accept_order(actor, order.pk, order.version)
            web.append(str(order.pk))
        result = {
            "batch": BATCH,
            "receipt_id": receipt.pk,
            "posted_sale_ids": posted,
            "draft_sale_id": draft.pk,
            "draft_receipt_id": receipt_draft.pk,
            "web_order_ids": web,
            "variant_ids": [v.pk for v in variants],
            "source_type": "SAMPLE",
            "research_data_changed": False,
        }
        audit(actor, "SEED_CURRENT_CATALOGUE", receipt, result, reason=NOTE)
        self.stdout.write(self.style.SUCCESS(json.dumps(result, ensure_ascii=False)))
