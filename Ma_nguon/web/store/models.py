from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Quản trị viên"
    SALES = "SALES", "Nhân viên bán hàng"
    WAREHOUSE = "WAREHOUSE", "Nhân viên kho"
    CUSTOMER = "CUSTOMER", "Khách hàng"


STAFF_ROLES = (Role.ADMIN, Role.SALES, Role.WAREHOUSE)
STAFF_ROLE_CHOICES = [(role, role.label) for role in STAFF_ROLES]


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    objects = UserManager()
    REQUIRED_FIELDS = ["full_name"]
    full_name = models.CharField("Họ tên", max_length=150)
    role = models.CharField("Vai trò", max_length=12, choices=Role.choices, default=Role.CUSTOMER)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("username"), name="user_username_ci"),
            models.CheckConstraint(condition=Q(role__in=Role.values), name="user_valid_role"),
            models.CheckConstraint(
                condition=~Q(role=Role.CUSTOMER) | Q(is_staff=False, is_superuser=False),
                name="customer_no_staff_flags",
            ),
        ]

    def save(self, *args, **kwargs):
        self.username = self.username.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name or self.username


class CustomerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="customer_profile")
    phone = models.CharField("Số điện thoại", max_length=25)


class WebGuestOwner(models.Model):
    """Serialize guest checkout against claiming that session's orders at login."""

    owner_hash = models.CharField(max_length=64, primary_key=True)
    account = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)


class CustomerLoginAttempt(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    failures = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField(default=timezone.now)


class Timestamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Catalog(Timestamped):
    code = models.CharField("Mã", max_length=80, unique=True)
    name = models.CharField("Tên", max_length=200)
    is_active = models.BooleanField("Đang sử dụng", default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True
        ordering = ["code"]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} · {self.name}"


class Category(Catalog):
    pass


class Brand(Catalog):
    pass


class Size(Catalog):
    pass


class Color(Catalog):
    pass


class Product(Catalog):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name="Danh mục")
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, verbose_name="Thương hiệu")
    unit = models.CharField("Đơn vị", max_length=20)


class Variant(Timestamped):
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="variants", verbose_name="Sản phẩm"
    )
    size = models.ForeignKey(Size, on_delete=models.PROTECT, verbose_name="Kích thước")
    color = models.ForeignKey(Color, on_delete=models.PROTECT, verbose_name="Màu")
    sku = models.CharField("Mã biến thể", max_length=80, unique=True)
    selling_price = models.DecimalField(
        "Giá bán (đồng)", max_digits=18, decimal_places=0, validators=[MinValueValidator(0)]
    )
    low_stock_threshold = models.PositiveIntegerField("Ngưỡng cảnh báo", null=True, blank=True)
    is_active = models.BooleanField("Đang kinh doanh", default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["sku"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "size", "color"], name="variant_combination_unique"
            ),
            models.CheckConstraint(
                condition=Q(selling_price__gte=0, selling_price__lt=10**18),
                name="variant_price_nonnegative",
            ),
        ]

    def save(self, *args, **kwargs):
        self.sku = self.sku.strip().upper()
        with transaction.atomic():
            super().save(*args, **kwargs)
            StockBalance.objects.get_or_create(variant=self)

    def __str__(self):
        return f"{self.sku} · {self.product.name} · {self.size.name} / {self.color.name}"


class Customer(Catalog):
    phone = models.CharField("Điện thoại", max_length=25, blank=True)
    note = models.TextField("Ghi chú", blank=True)


class Supplier(Catalog):
    phone = models.CharField("Điện thoại", max_length=25, blank=True)
    address = models.TextField("Địa chỉ", blank=True)


class StockPosting(models.Model):
    kind = models.CharField(
        max_length=20,
        choices=[(s, s) for s in ["OPENING", "RECEIPT", "SALE", "ADJUSTMENT", "CORRECTION"]],
    )
    business_key = models.CharField(max_length=100, unique=True)
    posted_by = models.ForeignKey(User, on_delete=models.PROTECT)
    posted_at = models.DateTimeField(default=timezone.now, db_index=True)


class Status(models.TextChoices):
    DRAFT = "DRAFT", "Nháp"
    POSTED = "POSTED", "Đã xác nhận"
    CANCELLED = "CANCELLED", "Đã hủy nháp"


class Document(Timestamped):
    code = models.CharField(max_length=30, unique=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="%(class)s_created")
    posted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="%(class)s_posted"
    )
    posted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cancel_reason = models.TextField(blank=True)
    stock_posting = models.OneToOneField(
        StockPosting, null=True, blank=True, on_delete=models.PROTECT, related_name="%(class)s"
    )

    class Meta:
        abstract = True
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status="POSTED",
                        posted_by__isnull=False,
                        posted_at__isnull=False,
                        stock_posting__isnull=False,
                    )
                    | Q(
                        status__in=["DRAFT", "CANCELLED"],
                        posted_by__isnull=True,
                        posted_at__isnull=True,
                        stock_posting__isnull=True,
                    )
                ),
                name="%(class)s_state_consistent",
            )
        ]

    def __str__(self):
        return self.code


class SupplierOrder(Timestamped):
    reference = models.CharField("Mã đặt nhà cung cấp", max_length=80)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, verbose_name="Nhà cung cấp")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, verbose_name="Biến thể")
    ordered_qty = models.PositiveIntegerField("Số lượng đặt")
    expected_on = models.DateField("Ngày dự kiến nhận")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(ordered_qty__gt=0), name="supplier_order_positive_qty"
            ),
            models.UniqueConstraint(
                fields=["supplier", "reference", "variant"], name="supplier_order_unique_line"
            ),
        ]


class GoodsReceipt(Document):
    supplier_order = models.ForeignKey(
        SupplierOrder, on_delete=models.PROTECT, null=True, blank=True, related_name="receipts"
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, verbose_name="Nhà cung cấp")
    supplier_name_snapshot = models.CharField(max_length=200, blank=True)
    delivery_reference = models.CharField("Tham chiếu giao hàng", max_length=100, blank=True)
    total_amount = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    note = models.TextField("Ghi chú", blank=True)

    class Meta(Document.Meta):
        abstract = False
        constraints = Document.Meta.constraints + [
            models.CheckConstraint(
                condition=Q(total_amount__gte=0, total_amount__lt=10**18),
                name="receipt_total_valid",
            )
        ]


class SaleOrder(Document):
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Khách hàng"
    )
    customer_name_snapshot = models.CharField(max_length=200, default="Khách lẻ")
    total_amount = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    replacement_for = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)

    class Meta(Document.Meta):
        abstract = False
        constraints = Document.Meta.constraints + [
            models.CheckConstraint(
                condition=Q(total_amount__gte=0, total_amount__lt=10**18), name="sale_total_valid"
            )
        ]


class Line(models.Model):
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    sku_snapshot = models.CharField(max_length=80, blank=True)
    name_snapshot = models.CharField(max_length=200, blank=True)
    variant_snapshot = models.CharField(max_length=150, blank=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="%(class)s_qty_positive")
        ]

    @property
    def line_total(self):
        return self.quantity * (self.unit_cost if hasattr(self, "unit_cost") else self.unit_price)


class ReceiptLine(Line):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="lines")
    unit_cost = models.DecimalField(
        max_digits=18, decimal_places=0, validators=[MinValueValidator(0)]
    )

    class Meta(Line.Meta):
        abstract = False
        constraints = Line.Meta.constraints + [
            models.UniqueConstraint(fields=["receipt", "variant"], name="receipt_sku_unique"),
            models.CheckConstraint(
                condition=Q(unit_cost__gte=0, unit_cost__lt=10**18),
                name="receipt_cost_nonnegative",
            ),
        ]


class SaleLine(Line):
    sale = models.ForeignKey(SaleOrder, on_delete=models.PROTECT, related_name="lines")
    unit_price = models.DecimalField(
        max_digits=18, decimal_places=0, validators=[MinValueValidator(1)]
    )

    class Meta(Line.Meta):
        abstract = False
        constraints = Line.Meta.constraints + [
            models.UniqueConstraint(fields=["sale", "variant"], name="sale_sku_unique"),
            models.CheckConstraint(
                condition=Q(unit_price__gt=0, unit_price__lt=10**18), name="sale_price_positive"
            ),
        ]


class SalePayment(models.Model):
    sale = models.OneToOneField(SaleOrder, on_delete=models.PROTECT, related_name="payment")
    method = models.CharField(
        max_length=10,
        choices=[
            ("CASH", "Tiền mặt"),
            ("TRANSFER", "Chuyển khoản ghi nhận thủ công"),
            ("VNPAY", "VNPAY"),
        ],
    )
    amount = models.DecimalField(max_digits=18, decimal_places=0)
    cash_received = models.DecimalField(max_digits=18, decimal_places=0, null=True, blank=True)
    change_amount = models.DecimalField(max_digits=18, decimal_places=0, null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0, amount__lt=10**18), name="payment_amount_nonnegative"
            ),
            models.CheckConstraint(
                condition=(
                    Q(cash_received__isnull=True)
                    | Q(cash_received__gte=0, cash_received__lt=10**18)
                )
                & (
                    Q(change_amount__isnull=True)
                    | Q(change_amount__gte=0, change_amount__lt=10**18)
                ),
                name="payment_cash_finite",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        method="CASH",
                        cash_received__isnull=False,
                        change_amount__isnull=False,
                        cash_received__gte=models.F("amount"),
                        change_amount=models.F("cash_received") - models.F("amount"),
                    )
                    | Q(
                        method__in=["TRANSFER", "VNPAY"],
                        cash_received__isnull=True,
                        change_amount__isnull=True,
                    )
                ),
                name="payment_method_values",
            ),
        ]


class StockBalance(models.Model):
    variant = models.OneToOneField(
        Variant, primary_key=True, on_delete=models.PROTECT, related_name="balance"
    )
    quantity = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class StockEntry(models.Model):
    posting = models.ForeignKey(StockPosting, on_delete=models.PROTECT, related_name="entries")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="stock_entries")
    delta = models.IntegerField()

    class Meta:
        ordering = ["posting_id", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["posting", "variant"], name="entry_sku_unique"),
            models.CheckConstraint(condition=~Q(delta=0), name="entry_nonzero"),
        ]


class StockAdjustment(Document):
    kind = models.CharField(
        max_length=10, choices=[("OPENING", "Tồn đầu kỳ"), ("COUNT", "Kiểm đếm")]
    )
    reason = models.TextField("Lý do và căn cứ")
    source_reference = models.CharField("Tham chiếu kiểm đếm", max_length=100, blank=True)


class AdjustmentLine(models.Model):
    adjustment = models.ForeignKey(StockAdjustment, on_delete=models.PROTECT, related_name="lines")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    expected_qty = models.PositiveIntegerField()
    expected_version = models.PositiveIntegerField()
    counted_qty = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["adjustment", "variant"], name="adjustment_sku_unique")
        ]


class DocumentCorrection(Document):
    original_sale = models.ForeignKey(
        SaleOrder, on_delete=models.PROTECT, null=True, blank=True, related_name="corrections"
    )
    original_receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.PROTECT, null=True, blank=True, related_name="corrections"
    )
    reason = models.TextField()
    evidence = models.TextField()
    goods_recovered_ack = models.BooleanField(default=False)
    financial_ack = models.BooleanField(default=False)
    amount_snapshot = models.DecimalField(max_digits=18, decimal_places=0, default=0)

    class Meta(Document.Meta):
        abstract = False
        constraints = Document.Meta.constraints + [
            models.CheckConstraint(
                condition=(
                    Q(original_sale__isnull=False, original_receipt__isnull=True)
                    | Q(original_sale__isnull=True, original_receipt__isnull=False)
                ),
                name="correction_one_original",
            ),
            models.UniqueConstraint(
                fields=["original_sale"],
                condition=Q(status="POSTED"),
                name="one_posted_sale_correction",
            ),
            models.UniqueConstraint(
                fields=["original_receipt"],
                condition=Q(status="POSTED"),
                name="one_posted_receipt_correction",
            ),
        ]


class OperationRequest(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    operation = models.CharField(max_length=40)
    request_key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    result_type = models.CharField(max_length=40)
    result_id = models.BigIntegerField()
    completed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["actor", "operation", "request_key"], name="operation_key_unique"
            )
        ]


class AuditEvent(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=60)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=80)
    changed_fields = models.JSONField(default=dict)
    reason = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-pk"]


class SystemGuard(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    version = models.PositiveIntegerField(default=1)
    data_mode = models.CharField(
        max_length=12,
        choices=[("DEMO", "Minh họa"), ("OPERATIONAL", "Vận hành")],
        default="OPERATIONAL",
    )
    initialized_at = models.DateTimeField(default=timezone.now)


class ShopLocation(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    address = models.CharField(max_length=200, blank=True)
    is_example = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="shop_location_singleton"),
            models.CheckConstraint(
                condition=Q(is_example=False) | ~Q(address=""), name="shop_example_has_address"
            ),
        ]


class SourceType(models.TextChoices):
    RESEARCH = "RESEARCH", "Nghiên cứu hồi cứu"
    OPERATIONAL = "OPERATIONAL", "Dữ liệu cửa hàng"
    DEMO = "DEMO", "Minh họa chức năng"


class DatasetVersion(Timestamped):
    code = models.CharField(max_length=50, unique=True)
    source_type = models.CharField(max_length=12, choices=SourceType.choices)
    manifest_hash = models.CharField(max_length=64)
    coverage_start = models.DateField()
    coverage_end = models.DateField()
    scope_definition = models.JSONField(default=dict)
    cleaning_config = models.JSONField(default=dict)
    status = models.CharField(
        max_length=12, choices=[(s, s) for s in ["DRAFT", "VALIDATED", "FAILED"]], default="DRAFT"
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)


class SourceFile(models.Model):
    dataset_version = models.ForeignKey(
        DatasetVersion, on_delete=models.PROTECT, related_name="source_files"
    )
    relative_name = models.TextField()
    sha256 = models.CharField(max_length=64)
    row_count = models.PositiveIntegerField()
    schema_version = models.CharField(max_length=30)
    validation_status = models.CharField(max_length=15)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset_version", "sha256"], name="source_hash_unique")
        ]


class ForecastUnit(models.Model):
    dataset_version = models.ForeignKey(
        DatasetVersion, on_delete=models.PROTECT, related_name="forecast_units"
    )
    external_key = models.CharField(max_length=100)
    label = models.CharField(max_length=200, blank=True)
    granularity = models.CharField(
        max_length=10, choices=[("SKU", "Mã hàng nguồn"), ("PRODUCT", "Sản phẩm")]
    )
    unit = models.CharField(max_length=20)
    scope_key = models.CharField(max_length=100)
    internal_product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)
    mapping_status = models.CharField(max_length=12, default="UNVERIFIED")
    mapping_evidence = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_version", "external_key"], name="forecast_unit_unique"
            )
        ]


class ExternalSkuMap(models.Model):
    forecast_unit = models.ForeignKey(
        ForecastUnit, on_delete=models.PROTECT, related_name="external_skus"
    )
    external_product_id = models.CharField(max_length=100)
    internal_variant = models.ForeignKey(Variant, on_delete=models.PROTECT, null=True, blank=True)
    evidence = models.TextField(blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["forecast_unit", "external_product_id"], name="external_map_unique"
            )
        ]


class MonthlySales(models.Model):
    forecast_unit = models.ForeignKey(
        ForecastUnit, on_delete=models.PROTECT, related_name="monthly_sales"
    )
    month = models.DateField()
    positive_qty = models.DecimalField(max_digits=18, decimal_places=4)
    negative_qty_abs = models.DecimalField(max_digits=18, decimal_places=4)
    net_qty = models.DecimalField(max_digits=18, decimal_places=4)
    target_qty = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    observation_status = models.CharField(max_length=15)
    source_row_count = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["forecast_unit", "month"], name="monthly_unit_unique"),
            models.CheckConstraint(condition=Q(month__day=1), name="monthly_first_day"),
            models.CheckConstraint(
                condition=Q(
                    positive_qty__gte=0,
                    positive_qty__lt=10**14,
                    negative_qty_abs__gte=0,
                    negative_qty_abs__lt=10**14,
                ),
                name="monthly_nonnegative_flows",
            ),
            models.CheckConstraint(
                condition=Q(
                    net_qty=models.F("positive_qty") - models.F("negative_qty_abs"),
                    net_qty__gt=-(10**14),
                    net_qty__lt=10**14,
                ),
                name="monthly_net_reconciles",
            ),
            models.CheckConstraint(
                condition=Q(target_qty__isnull=True) | Q(target_qty__gte=0, target_qty__lt=10**14),
                name="monthly_target_valid",
            ),
        ]


class Experiment(Timestamped):
    dataset_version = models.ForeignKey(
        DatasetVersion, on_delete=models.PROTECT, related_name="experiments"
    )
    target_definition = models.JSONField(default=dict)
    eligibility_policy = models.JSONField(default=dict)
    split_config = models.JSONField(default=dict)
    feature_spec = models.JSONField(default=dict)
    model_configs = models.JSONField(default=dict)
    random_seed = models.IntegerField(default=42)
    status = models.CharField(max_length=12, default="DRAFT")


class ModelResult(models.Model):
    experiment = models.ForeignKey(
        Experiment, on_delete=models.PROTECT, related_name="model_results"
    )
    method = models.CharField(max_length=20)
    selected_on_validation = models.BooleanField(default=False)
    validation_metrics = models.JSONField(default=dict)
    test_metrics = models.JSONField(default=dict)
    scored_pair_manifest = models.JSONField(default=dict)
    artifact_path = models.TextField(blank=True)
    artifact_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "method"], name="experiment_method_unique"
            ),
            models.UniqueConstraint(
                fields=["experiment"],
                condition=Q(selected_on_validation=True),
                name="one_selected_method",
            ),
        ]


class ForecastRun(models.Model):
    model_result = models.ForeignKey(ModelResult, on_delete=models.PROTECT, related_name="runs")
    cutoff_month = models.DateField()
    target_month = models.DateField()
    scope_key = models.CharField(max_length=100)
    status = models.CharField(max_length=12, default="RUNNING")
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True)


class ForecastValue(models.Model):
    run = models.ForeignKey(ForecastRun, on_delete=models.PROTECT, related_name="values")
    forecast_unit = models.ForeignKey(
        ForecastUnit, on_delete=models.PROTECT, related_name="forecasts"
    )
    raw_value = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    nonnegative_value = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    result_status = models.CharField(max_length=20)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "forecast_unit"], name="forecast_value_unique"),
            models.CheckConstraint(
                condition=Q(nonnegative_value__gte=0, nonnegative_value__lt=10**14)
                | Q(nonnegative_value__isnull=True),
                name="forecast_nonnegative",
            ),
            models.CheckConstraint(
                condition=~Q(result_status="VALID") | Q(nonnegative_value__isnull=False),
                name="valid_forecast_has_value",
            ),
            models.CheckConstraint(
                condition=Q(raw_value__isnull=True)
                | Q(raw_value__gt=-(10**14), raw_value__lt=10**14),
                name="forecast_raw_finite",
            ),
        ]


class ReplenishmentPolicy(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="policies")
    safety_stock_qty = models.PositiveIntegerField()
    effective_from = models.DateTimeField(default=timezone.now)
    effective_to = models.DateTimeField(null=True)
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(effective_to__isnull=True),
                name="one_current_policy",
            )
        ]


class ReplenishmentSuggestion(Timestamped):
    forecast_value = models.ForeignKey(
        ForecastValue, on_delete=models.PROTECT, related_name="suggestions"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    inventory_qty_snapshot = models.PositiveIntegerField()
    inventory_versions = models.JSONField(default=dict)
    inventory_as_of = models.DateTimeField()
    safety_stock_snapshot = models.PositiveIntegerField()
    suggested_qty = models.PositiveIntegerField()
    status = models.CharField(max_length=15)
    generated_by = models.ForeignKey(User, on_delete=models.PROTECT)


class WebOrderQuerySet(models.QuerySet):
    def with_lifecycle(self):
        return self.annotate(
            _db_lifecycle_status=models.Func(
                models.F("pk"),
                function="public.nep_web_lifecycle",
                output_field=models.CharField(),
            )
        )


from store.services.payment_preferences import PAYMENT_PREFERENCE_CHOICES


class WebOrder(Timestamped):
    """Purchase request; only a posted staff sale can change inventory."""

    LIFECYCLE_LABELS = {
        "PENDING": "Chờ xác nhận",
        "ACCEPTED": "Đã tiếp nhận",
        "COMPLETED": "Đã hoàn tất tại cửa hàng",
        "CANCELLED": "Đã hủy",
        "SALE_CANCELLED": "Cửa hàng đã hủy đơn bán",
        "CORRECTED": "Đơn bán đã được sửa sai toàn bộ",
    }

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    code = models.CharField(max_length=30, unique=True)
    request_key = models.UUIDField(unique=True)
    owner_hash = models.CharField(max_length=64, db_index=True)
    account = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="web_orders"
    )
    payload_hash = models.CharField(max_length=64)
    customer_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=25)
    note = models.CharField(max_length=1000, blank=True)
    payment_preference = models.CharField(
        "Phương thức khách chọn",
        max_length=12,
        choices=PAYMENT_PREFERENCE_CHOICES,
        default="UNSPECIFIED",
        db_default="UNSPECIFIED",
    )
    status = models.CharField(
        max_length=12,
        default="PENDING",
        choices=[
            ("PENDING", "Chờ xác nhận"),
            ("ACCEPTED", "Đã tiếp nhận"),
            ("CANCELLED", "Đã hủy"),
        ],
        db_index=True,
    )
    total_amount = models.DecimalField(max_digits=18, decimal_places=0)
    sale = models.OneToOneField(
        SaleOrder, on_delete=models.PROTECT, null=True, blank=True, related_name="web_order"
    )
    handled_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)
    handled_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=1000, blank=True)
    cancel_origin = models.CharField(
        max_length=10, blank=True, choices=[("CUSTOMER", "Khách hàng"), ("STAFF", "Nhân viên")]
    )
    version = models.PositiveIntegerField(default=1)

    pickup_expires_at = models.DateTimeField(null=True, blank=True)
    pickup_address = models.CharField(max_length=200, blank=True, db_default="")
    pickup_address_is_example = models.BooleanField(db_default=False)
    delivery_address = models.CharField(max_length=350, blank=True, db_default="")
    tracking_number = models.CharField(max_length=100, blank=True, db_default="")
    shipment_status = models.CharField(
        max_length=12,
        blank=True,
        db_default="",
        choices=[("SHIPPED", "Đang giao"), ("DELIVERED", "Đã giao")],
    )

    objects = WebOrderQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_amount__gt=0, total_amount__lt=10**18),
                name="web_order_total_positive",
            ),
            models.CheckConstraint(
                condition=Q(payment_preference__in=["UNSPECIFIED", "CASH", "TRANSFER", "VNPAY"]),
                name="web_payment_preference_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(pickup_address="", pickup_address_is_example=False)
                    | (Q(delivery_address="") & ~Q(pickup_address=""))
                ),
                name="web_pickup_address_valid",
            ),
            models.CheckConstraint(
                condition=(Q(delivery_address="") | Q(payment_preference="VNPAY"))
                & (
                    Q(shipment_status="", tracking_number="")
                    | (
                        Q(shipment_status__in=["SHIPPED", "DELIVERED"], status="ACCEPTED")
                        & ~Q(delivery_address="")
                        & ~Q(tracking_number="")
                    )
                ),
                name="web_shipment_fields_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="ACCEPTED",
                        sale__isnull=False,
                        handled_by__isnull=False,
                        handled_at__isnull=False,
                    )
                    | Q(status__in=["PENDING", "CANCELLED"], sale__isnull=True)
                ),
                name="web_order_state_valid",
            ),
        ]

    @property
    def lifecycle_status(self):
        if "_db_lifecycle_status" in self.__dict__:
            return self._db_lifecycle_status
        return (
            type(self)
            .objects.using(self._state.db)
            .with_lifecycle()
            .values_list("_db_lifecycle_status", flat=True)
            .get(pk=self.pk)
        )

    @property
    def sale_was_corrected(self):
        return self.lifecycle_status == "CORRECTED"

    @property
    def display_status(self):
        lifecycle = self.lifecycle_status
        if lifecycle == "COMPLETED" and self.payment_preference == "VNPAY":
            if self.delivery_address:
                return self.get_shipment_status_display() or "Đã thanh toán, đang chuẩn bị giao"
            return "Đã thanh toán, nhận tại cửa hàng"
        return self.LIFECYCLE_LABELS[lifecycle]


class GatewayPayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    order = models.OneToOneField(WebOrder, on_delete=models.PROTECT, related_name="gateway_payment")
    amount = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(default=timezone.now)
    client_ip = models.GenericIPAddressField()
    status = models.CharField(
        max_length=10,
        default="WAITING",
        choices=[
            ("WAITING", "Chờ thanh toán"),
            ("FAILED", "Giao dịch không thành công"),
            ("REVIEW", "Đã thu tiền, cần đối chiếu"),
            ("POSTED", "Đã thanh toán"),
        ],
    )
    provider_reference = models.CharField(max_length=32, null=True, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0, amount__lt=10**10),
                name="gateway_amount_vnd",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["WAITING", "FAILED"], provider_reference__isnull=True)
                | (
                    Q(status__in=["REVIEW", "POSTED"], provider_reference__isnull=False)
                    & ~Q(provider_reference="")
                ),
                name="gateway_result_valid",
            ),
        ]


class WebOrderLine(models.Model):
    order = models.ForeignKey(WebOrder, on_delete=models.PROTECT, related_name="lines")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=18, decimal_places=0)
    name_snapshot = models.CharField(max_length=200)
    sku_snapshot = models.CharField(max_length=80)
    variant_snapshot = models.CharField(max_length=150)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "variant"], name="web_order_variant_unique"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0, quantity__lte=99), name="web_order_quantity_valid"
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gt=0, unit_price__lt=10**18),
                name="web_order_line_price_positive",
            ),
        ]

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class ShopPost(Timestamped):
    title = models.CharField("Tiêu đề", max_length=160)
    summary = models.CharField("Đoạn giới thiệu", max_length=280)
    body = models.TextField("Nội dung", max_length=12000)
    published_at = models.DateTimeField("Ngày đăng", null=True, blank=True, db_index=True)
