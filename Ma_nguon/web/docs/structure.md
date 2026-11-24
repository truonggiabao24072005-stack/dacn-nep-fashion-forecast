# Cấu trúc mã nguồn

Cách phân chia trách nhiệm tham khảo `C:/MULTIPLEPLATFROM/lesson02/WebApp`: Controllers xử lý yêu cầu, Models mô tả dữ liệu và Services xử lý nghiệp vụ. Trong Django, phần xử lý yêu cầu mang tên views; truy cập dữ liệu dùng ORM.

| Vị trí | Nội dung |
|---|---|
| config/ | Cấu hình, URL gốc và khởi động Django |
| store/models.py | Mô hình và ràng buộc CSDL |
| store/views/ | Trang quản lý, mua hàng, tài khoản, tin tức và thanh toán |
| store/forms/ | Biểu mẫu theo nghiệp vụ |
| store/services/ | Chứng từ, tài khoản, danh mục, đơn hàng, nhà cung cấp và VNPAY |
| store/forecast/ | Đặc trưng, thực nghiệm, dự đoán, Metrics và lượng nhập đề xuất |
| store/data/ | Danh mục, thông tin nguồn ảnh và các đợt nhập danh mục |
| store/migrations/ | Lịch sử cấu trúc PostgreSQL |
| store/management/commands/ | Lệnh nhập dữ liệu, chạy dự báo, đối soát và khởi tạo |
| store/tests/ | Kiểm thử nghiệp vụ, quyền, SQL và dự báo |
| templates/ | HTML theo khu khách hàng hoặc quản lý, rồi theo chức năng |
| static/ | CSS, JavaScript, ảnh và biểu tượng |
| tools/ | Chạy web, kiểm tra tệp, quản trị PostgreSQL và kiểm chứng |

Cơ sở dữ liệu được bàn giao bằng một tệp query SQL thuần duy nhất (`CSDL_dacn_truong_gia_bao_1250080020.sql`) chạy trực tiếp trên pgAdmin Query Tool, tách riêng khỏi mã nguồn website.

Phần huấn luyện độc lập ở `../nghien_cuu/`: `du_lieu.py` đọc và kiểm tra dữ liệu, `train.py` điều phối huấn luyện và đánh giá, `huan_luyen_nhu_cau.ipynb` trình bày theo từng bước. `tools/train_forecast.py` là lệnh mở phần này từ website. Tính toán tạo mẫu, biến đổi và huấn luyện nằm chung trong `store/forecast/training.py`; `features.py` và `research.py` giữ giao diện gọi của nghiệp vụ website.

## Quy tắc đặt tên

Tên tệp và hàm dùng snake_case; tên lớp dùng PascalCase. Biểu mẫu kết thúc bằng Form, lớp trang đăng nhập kết thúc bằng View. Ví dụ: `DocumentLineForm`, `ConfirmDocumentForm`, `CustomerRegistrationForm`, `EmployeeLoginView`.
Tên trường trong CSDL, mã sản phẩm, URL và tên tuyến được giữ nguyên. Một biểu mẫu chỉ nhận và kiểm tra đầu vào; phần ghi chứng từ hoặc thay đổi tồn kho gọi hàm nghiệp vụ trong services.
Hàm chung về quyền truy cập và ngữ cảnh giao diện ở `store/views/common.py`. Biểu mẫu dùng chung ở `store/forms/documents.py`; các đoạn HTML dùng lại ở thư mục shared hoặc partials.
