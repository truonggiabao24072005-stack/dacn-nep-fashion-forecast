# Sử dụng website

## Khu mua hàng

Khách tra cứu sản phẩm, chọn cỡ và màu, thêm vào giỏ rồi kiểm tra lại thông tin khi đặt hàng. Tài khoản khách dùng để xem yêu cầu của mình; yêu cầu của khách chưa đăng nhập gắn với phiên trình duyệt.
Khi tiếp nhận tại cửa hàng, nhân viên đối chiếu giá và hàng trước khi hoàn tất. Chỉ chứng từ đã ghi sổ mới làm thay đổi số dư kho. Trường hợp VNPAY và giao hàng xem trong payments.md.

## Khu quản lý

Quản trị quản lý nhân viên, danh mục và cấu hình. Nhân viên bán hàng tiếp nhận đơn, bán hàng và xử lý phần được phân quyền. Nhân viên kho nhập hàng, theo dõi biến thể và chứng từ theo quyền.
Thêm sản phẩm không tự tăng tồn. Dùng phiếu nhập hoặc kiểm đếm có căn cứ, xác nhận số lượng rồi ghi sổ. Cỡ, màu, mã biến thể và trạng thái kinh doanh được đối chiếu cùng nhau khi mở bán.
Chứng từ nháp có thể chỉnh sửa. Chứng từ đã ghi sổ giữ lịch sử; sai sót được xử lý qua chứng từ bù trừ, không sửa trực tiếp dòng đã ghi.

## Dự báo và nhập hàng

Trang dự báo trình bày nhu cầu theo sản phẩm, tháng và biểu đồ so với thực tế. Tháng chưa có Actual giữ trống sai số. Kết quả nghiên cứu 2022–2023 không tự tạo tồn kho hoặc thay dữ liệu bán.
Gợi ý nhập theo biến thể đọc lịch sử và tồn bán được, tồn an toàn cùng lượng nhà cung cấp dự kiến giao. Nhân viên phải đối chiếu điều kiện dữ liệu, cỡ, màu và lịch giao trước khi đặt mua; gợi ý chưa phải phiếu nhập đã ghi sổ.

## Kiểm tra

Chạy `test.ps1` trên CSDL kiểm thử riêng. Nhật ký lần chạy được ghi trong `.runtime/evidence/`. Dùng `database.ps1` hoặc phần truy vấn đối soát ở cuối tệp `CSDL_dacn_truong_gia_bao_1250080020.sql` trong pgAdmin để đối chiếu tiền, chứng từ và sổ kho.
