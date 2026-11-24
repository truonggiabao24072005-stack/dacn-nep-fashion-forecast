# Website Nếp

Website mua hàng và quản lý cửa hàng giày dép, xây dựng bằng Django và PostgreSQL.

## Chạy ứng dụng

Tạo môi trường Python, cài `requirements.txt`, tạo `.env` theo `.env.example` và nạp CSDL bằng tệp query SQL duy nhất (`CSDL_dacn_truong_gia_bao_1250080020.sql`) trên pgAdmin 4 (PostgreSQL 18), không chạy tệp SQL từ trong mã nguồn và không dùng Restore/`pg_restore`:

1. Trong pgAdmin, tạo database rỗng tên `dacn_truong_gia_bao` (chuột phải `Databases > Create > Database...`, giữ Encoding `UTF8`, bấm Save; hoặc chạy lệnh `CREATE DATABASE dacn_truong_gia_bao WITH TEMPLATE = template0 ENCODING = 'UTF8';` tại database `postgres`).
2. Refresh mục `Databases`, chọn đúng `dacn_truong_gia_bao`, mở `Tools > Query Tool`, bật **Auto commit**, mở tệp duy nhất `CSDL_dacn_truong_gia_bao_1250080020.sql` và nhấn **F5** để chạy toàn bộ (tạo cấu trúc, nạp đầy đủ dữ liệu và chạy bảng đối soát 11 chỉ tiêu với `so_loi = 0`).
3. Trong `.env`, điền `DB_NAME=dacn_truong_gia_bao`, `DB_USER` (tài khoản PostgreSQL đã dùng chạy SQL, ví dụ `postgres`), `DB_PASSWORD`, `DB_HOST=127.0.0.1`, `DB_PORT` (thường là `5432`) và `DJANGO_SECRET_KEY`. Xem chi tiết tại `CSDL/HUONG_DAN_CHAY_POSTGRESQL.txt`.

Sau đó chạy:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py check
python manage.py runserver 127.0.0.1:8891
```

Trang mua hàng: http://127.0.0.1:8891/. Trang quản lý: http://127.0.0.1:8891/quan-tri/ (đăng nhập bằng tài khoản quản trị vừa tạo bằng `createsuperuser`).
Trên máy đã có môi trường và CSDL cục bộ, có thể dùng `run.ps1`. Dùng `test.ps1` để kiểm thử và `database.ps1` để đối soát dữ liệu khi ứng dụng đang chạy.

## Tổ chức mã

`store/views/` xử lý các trang và yêu cầu; `store/forms/` khai báo biểu mẫu; `store/services/` xử lý nghiệp vụ; `store/forecast/` chứa dự báo và gợi ý nhập. Mô hình CSDL nằm trong `store/models.py`, lịch sử cấu trúc trong `store/migrations/`.
Các trang HTML nằm trong `templates/shop/` và `templates/store/`, được chia tiếp theo chức năng. Ảnh, CSS, JavaScript nằm trong `static/`. Cấu hình danh mục và nguồn ảnh ở `store/data/`.

## Dữ liệu

Tệp nguồn, dữ liệu huấn luyện và kết quả mô hình được giữ ngoài mã website. Khi bàn giao, chúng nằm trong `Du_lieu/` cạnh thư mục `Ma_nguon/`.
Có thể đổi vị trí bằng các biến trong `.env`: `DACN_DATA_DIR`, `RESEARCH_RESULTS_DIR`, `RESEARCH_ARTIFACTS_DIR`. Các lệnh nghiên cứu đọc nguồn từ `DACN_SOURCE_DIR` nếu được thiết lập.
Nhật ký kiểm tra, bản sao cục bộ và tệp sinh khi chạy nằm trong `.runtime/`; không đưa thư mục này hoặc `.env` lên kho mã.

Xem `docs/structure.md`, `docs/usage.md` và `docs/payments.md` để tra cứu chi tiết.

## Chạy phần huấn luyện riêng

```powershell
python -m pip install -r ../nghien_cuu/requirements.txt
python tools/train_forecast.py --verify-reference
```

Công cụ đọc CSV tại `Du_lieu` cạnh `Ma_nguon`, không cần CSDL hoặc `.env`. Dùng `--data-dir` nếu dữ liệu nằm nơi khác; `--product MH00381` chọn biểu đồ sản phẩm. Mỗi lần chạy ghi tệp mới, không ghi đè dữ liệu đã chốt. Xem `../nghien_cuu/README.md` và notebook để thực hiện từng bước.

Trang `/du-bao/nghien-cuu/` dùng chung mã tính toán trong `store/forecast/training.py`, hiển thị lượng dự đoán, thực tế, chênh lệch và biểu đồ theo tháng. Nút tải bảng đối chiếu xuất riêng sản phẩm đang chọn; tháng chưa có thực tế để trống. Chỉ quản trị viên được cập nhật kết quả; nhân viên kho được xem và tải bảng.

## Giá bán VND

Giá bán hiện hành được làm tròn theo nghìn đồng khi nhập danh mục nguồn. Dữ liệu nguồn, giá trên đơn đã gửi và chứng từ đã ghi sổ được giữ nguyên. Cần kiểm tra lại giá nháp trước khi hoàn tất nếu danh mục vừa đổi.

Xem trước các giá cần điều chỉnh: `.venv/Scripts/python.exe manage.py cap_nhat_gia_vnd`. Áp dụng và ghi nhật ký: thêm `--apply`; tài khoản mặc định là admin, có thể chọn bằng `--username TEN_QUAN_TRI`. Lệnh chỉ đổi giá hiện hành, không sửa giá lịch sử.
