# Website Nếp

Website mua hàng và quản lý cửa hàng giày dép, xây dựng bằng Django và PostgreSQL.

## Chạy ứng dụng

Tạo môi trường Python, cài `requirements.txt`, tạo `.env` theo `.env.example` và phục hồi CSDL. Sau đó chạy:

```powershell
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check
python manage.py runserver 127.0.0.1:8891
```

Trang mua hàng: http://127.0.0.1:8891/. Trang quản lý: http://127.0.0.1:8891/quan-tri/.
Trên máy đã có môi trường và CSDL cục bộ, có thể dùng `run.ps1`. Dùng `test.ps1` để kiểm thử và `database.ps1` để đối soát, sao lưu hoặc phục hồi thử.

## Tổ chức mã

`store/views/` xử lý các trang và yêu cầu; `store/forms/` khai báo biểu mẫu; `store/services/` xử lý nghiệp vụ; `store/forecast/` chứa dự báo và gợi ý nhập. Mô hình CSDL nằm trong `store/models.py`, lịch sử cấu trúc trong `store/migrations/`.
Các trang HTML nằm trong `templates/shop/` và `templates/store/`, được chia tiếp theo chức năng. Ảnh, CSS, JavaScript nằm trong `static/`. Cấu hình danh mục và nguồn ảnh ở `store/data/`.

## Dữ liệu

Tệp nguồn, dữ liệu huấn luyện và kết quả mô hình được giữ ngoài mã website. Khi bàn giao, chúng nằm trong `Du_lieu/` cạnh thư mục `Ma_nguon/`.
Có thể đổi vị trí bằng các biến trong `.env`: `DACN_DATA_DIR`, `RESEARCH_RESULTS_DIR`, `RESEARCH_ARTIFACTS_DIR`. Các lệnh nghiên cứu đọc nguồn từ `DACN_SOURCE_DIR` nếu được thiết lập.
Nhật ký kiểm tra, bản sao cục bộ và tệp sinh khi chạy nằm trong `.runtime/`; không đưa thư mục này hoặc `.env` lên kho mã.

Xem `docs/structure.md`, `docs/usage.md`, `docs/payments.md` và `sql/README.md` để tra cứu chi tiết.

## Giá bán VND

Giá bán hiện hành được làm tròn theo nghìn đồng khi nhập danh mục nguồn. Dữ liệu nguồn, giá trên đơn đã gửi và chứng từ đã ghi sổ được giữ nguyên. Cần kiểm tra lại giá nháp trước khi hoàn tất nếu danh mục vừa đổi.

Xem trước các giá cần điều chỉnh: `.venv/Scripts/python.exe manage.py cap_nhat_gia_vnd`. Áp dụng và ghi nhật ký: thêm `--apply`; tài khoản mặc định là admin, có thể chọn bằng `--username TEN_QUAN_TRI`. Lệnh chỉ đổi giá hiện hành, không sửa giá lịch sử.
