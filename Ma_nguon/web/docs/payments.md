# Mua hàng qua website và VNPAY

## Đơn từ website

Khách thêm đúng biến thể theo cỡ, màu và số lượng còn bán. Danh mục lấy giá và trạng thái từ các biến thể khớp bộ lọc. Trang chủ ưu tiên hàng còn tồn và tách các sản phẩm đã xuất hiện ở nhóm nổi bật khỏi nhóm hàng mới.

Đơn nhận tại cửa hàng vẫn hỗ trợ tiền mặt hoặc chuyển khoản đối chiếu tại quầy. Khi VNPAY đã được cấu hình, khách có thể chọn thanh toán qua cổng này và nhập địa chỉ giao. Địa chỉ trống nghĩa là nhận tại cửa hàng. Đơn giao hàng hiện chỉ áp dụng với VNPAY. Tổng thu trong bản này là tổng tiền hàng, chưa có bảng phí theo vùng hay kết nối hãng vận chuyển. Nhân viên cần kiểm tra khả năng giao đến địa chỉ trước khi tiếp nhận đơn.

1. Khách gửi đơn, nhân viên kiểm tra giá và tồn, rồi tiếp nhận thành đơn bán nháp.
2. Khách mở **Đơn của tôi** và bấm thanh toán. Lượt thanh toán có thời hạn 15 phút.
3. IPN hợp lệ mới xác nhận tiền đã thu. Khi đơn còn đủ điều kiện, hệ thống ghi khoản thu và trừ kho trong một giao dịch PostgreSQL. IPN lặp lại không trừ kho lần hai.
4. Với đơn giao, nhân viên nhập mã vận đơn khi bàn giao và xác nhận đã giao khi có kết quả.
5. Nếu cổng đã thu tiền nhưng giá, tồn hoặc đơn bán đã thay đổi, đơn hiện **Đã thu tiền, cần đối chiếu**. Cửa hàng tra giao dịch theo mã VNPAY và xử lý trực tiếp. Cổng chưa có nút hoàn tiền hay cấp lại lượt thanh toán từ giao diện.

## Cấu hình thử

Chạy `python manage.py migrate` trước khi mở web. Dùng tài khoản merchant sandbox do VNPAY cấp. Đặt các biến sau trong môi trường chạy web.

```dotenv
VNPAY_TMN_CODE=
VNPAY_SECRET=
VNPAY_RETURN_URL=https://TEN-MIEN-THU/thanh-toan/vnpay/tro-ve/
VNPAY_SANDBOX=1
```

Đăng ký URL IPN `https://TEN-MIEN-THU/thanh-toan/vnpay/ipn/` với cổng. Cổng phải truy cập được IPN qua HTTPS. Việc khách quay lại Return URL chỉ chuyển về trang đơn. Cấu hình trống sẽ ẩn VNPAY. Không đưa khóa vào mã nguồn hoặc ảnh chụp. Chạy `python manage.py test store.tests.test_vnpay` với PostgreSQL để kiểm tra callback có chữ ký, sai số tiền, gửi lặp, quyền sở hữu và trường hợp thiếu tồn.

[Tài liệu kỹ thuật VNPAY](https://sandbox.vnpayment.vn/apis/docs/thanh-toan-pay/pay.html)
