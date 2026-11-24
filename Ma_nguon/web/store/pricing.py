"""Current retail prices in whole thousands of Vietnamese dong."""
from decimal import Decimal, ROUND_HALF_UP


def rounded_selling_price(amount):
    value = Decimal(str(amount))
    if not value.is_finite() or value <= 0:
        raise ValueError("Giá bán phải là số dương hữu hạn.")
    return max(Decimal(1000), (value / 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP) * 1000)
