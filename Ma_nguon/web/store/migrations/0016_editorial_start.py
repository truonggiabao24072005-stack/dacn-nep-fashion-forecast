from django.db import migrations
from django.utils import timezone


def publish_initial_posts(apps, schema_editor):
    posts = apps.get_model("store", "ShopPost").objects.using(schema_editor.connection.alias)
    articles = [
        (
            "Cách kiểm tra cỡ và tình trạng còn hàng",
            "Xem đúng màu, cỡ và trạng thái của mẫu bạn muốn đặt.",
            "Mở danh mục, chọn nhóm sản phẩm và lọc theo cỡ bạn thường đi. Nếu chỉ muốn xem hàng có thể đặt ngay, bật bộ lọc Chỉ xem hàng còn.\n\n"
            "Trên trang sản phẩm, chọn cỡ và màu trước khi thêm vào giỏ. Tình trạng còn hàng gắn với lựa chọn cụ thể. Nếu một cỡ đã hết, bạn có thể đổi lựa chọn hoặc quay lại danh mục.",
        ),
        (
            "Theo dõi đơn đặt trên website",
            "Xem cửa hàng đã tiếp nhận đơn và kiểm tra cách nhận hàng.",
            "Sau khi gửi yêu cầu, mở Đơn của tôi để xem trạng thái. Cửa hàng sẽ kiểm tra hàng và thông tin nhận trước khi tiếp nhận.\n\n"
            "Đăng nhập khi đặt giúp bạn tìm lại đơn trên các thiết bị khác. Với đơn giao có mã vận đơn, mã sẽ xuất hiện trong phần thông tin nhận hàng.",
        ),
    ]
    for title, summary, body in articles:
        posts.create(title=title, summary=summary, body=body, published_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("store", "0015_shop_post")]
    operations = [migrations.RunPython(publish_initial_posts, migrations.RunPython.noop)]

