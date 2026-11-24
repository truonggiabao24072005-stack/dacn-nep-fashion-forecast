from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def method_name(value):
    return {
        "naive": "Giá trị gần nhất",
        "ma3": "Trung bình ba tháng",
        "linear": "Hồi quy tuyến tính",
        "random_forest": "Rừng ngẫu nhiên hồi quy",
    }.get(value, value)


@register.filter
def vnd(value):
    try:
        return f"{Decimal(str(value)):,.0f}".replace(",", ".")
    except (ValueError, TypeError, InvalidOperation):
        return "Chưa có"


@register.filter
def number(value):
    if value is None:
        return "Chưa có"
    try:
        return f"{Decimal(str(value)):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    except (ValueError, TypeError, InvalidOperation):
        return value
