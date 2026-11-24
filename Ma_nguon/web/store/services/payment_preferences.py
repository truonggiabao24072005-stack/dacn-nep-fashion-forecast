"""Phương thức khách dự kiến sử dụng; khoản thu thực tế được lưu riêng."""

PAYMENT_METHOD_CHOICES = (
    ("CASH", "Tiền mặt tại quầy"),
    ("TRANSFER", "Chuyển khoản tại quầy"),
    ("VNPAY", "Thanh toán qua VNPAY"),
)
PAYMENT_PREFERENCE_CHOICES = (
    ("UNSPECIFIED", "Chưa chọn trong yêu cầu cũ"),
) + PAYMENT_METHOD_CHOICES


def normalise_payment_method(value):
    if value not in {code for code, _ in PAYMENT_METHOD_CHOICES}:
        raise ValueError("Phương thức thanh toán không hợp lệ.")
    return value
