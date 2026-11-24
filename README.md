# Nếp — Quản lý cửa hàng và dự báo nhu cầu

Đồ án chuyên ngành của Trương Gia Bảo: website mua giày dép, quản lý bán hàng, tồn kho theo SKU và nghiên cứu dự báo nhu cầu. Ứng dụng dùng Django và PostgreSQL.

## Thành phần

- `Ma_nguon/web`: website, nghiệp vụ, migrations, SQL, ảnh sản phẩm và kiểm thử.
- `Ma_nguon/nghien_cuu`: kiểm tra dữ liệu và chạy lại thực nghiệm dự báo.
- `Du_lieu/README.md`: nguồn dữ liệu và cách bố trí bộ dữ liệu được nộp cùng đồ án.

## Cài đặt và chạy

Môi trường đã dùng: Windows 11, Python 3.12.14, PostgreSQL 18.3. Các thư viện trực tiếp được cố định phiên bản trong `requirements.txt` của từng phần.

1. Tải mã và mở PowerShell tại `Ma_nguon/web`.
2. Tạo môi trường và cài thư viện:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(50))"
```

3. Điền chuỗi vừa tạo vào `DJANGO_SECRET_KEY` của `.env`. Điền `DB_NAME=dacn_truong_gia_bao`, `DB_USER` (tài khoản PostgreSQL đã dùng chạy SQL, ví dụ `postgres`), `DB_PASSWORD`, `DB_HOST=127.0.0.1`, `DB_PORT` (thường là `5432`) theo PostgreSQL trên máy nhận. Để chạy cục bộ, đặt `DJANGO_DEBUG=true`, giữ host `127.0.0.1,localhost`. Không đăng `.env` lên GitHub.
4. Nạp CSDL bằng SQL trực tiếp trong pgAdmin (PostgreSQL 18):

   - Mở Query Tool tại database `postgres`, bật Auto commit và chạy riêng `CSDL/00_tao_database.sql`.
   - Refresh Databases, chọn `dacn_truong_gia_bao` vừa tạo, mở Query Tool mới, bật Auto commit và chạy toàn bộ `CSDL/01_khoi_tao_he_thong.sql`.
   - Chạy `CSDL/02_kiem_tra_sau_khi_chay.sql` để đối chiếu.

   Hướng dẫn từng bước và cách xử lý lỗi ở `CSDL/HUONG_DAN_CHAY_POSTGRESQL.txt`. Bộ SQL đã có cấu trúc và dữ liệu; không cần dùng Restore hoặc `pg_restore`.

5. Đặt thư mục `Du_lieu` từ bộ hồ sơ nộp cạnh `Ma_nguon`. Có thể dùng biến `DACN_DATA_DIR` trong `.env` để chọn vị trí khác. Chạy:

```powershell
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py collectstatic --noinput
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8891
```

Trang mua hàng: http://127.0.0.1:8891/. Trang quản lý: http://127.0.0.1:8891/quan-tri/. Đăng nhập quản lý bằng tài khoản vừa tạo. Bộ tệp SQL CSDL không chứa mật khẩu rõ; không dùng tài khoản cũ làm tài khoản mặc định trên máy khác.

Nếu cài từ CSDL rỗng, xem `manage.py help khoi_tao_cua_hang` để khởi tạo danh mục; dữ liệu nghiên cứu và lịch sử giao dịch cần nạp riêng. Bộ SQL trong `CSDL` là cách tái hiện đầy đủ cấu trúc và dữ liệu của hồ sơ đã nộp.

## Kiểm tra và nghiên cứu

```powershell
.venv/Scripts/python.exe manage.py test store.tests
.venv/Scripts/python.exe -m pip install -r ../nghien_cuu/requirements.txt
.venv/Scripts/python.exe tools/train_forecast.py --verify-reference
```

Kiểm thử dùng CSDL riêng; tài khoản PostgreSQL cần quyền tạo CSDL kiểm thử. Hướng dẫn nghiệp vụ ở `Ma_nguon/web/docs/usage.md`, thanh toán ở `docs/payments.md`, quản lý CSDL ở `sql/README.md`.

## Phạm vi kết quả

Danh mục bán hàng có 51 mã được đối chiếu với SKU nguồn. Nghiên cứu dùng lịch sử 2022–2023, tách Training, Validation và Test theo thời gian. Random Forest trên 7.955 cặp Test có MAE 4,7908; RMSE 14,0278; WAPE 55,8406%; Coverage 22,57%. Đây là kết quả nghiên cứu lịch sử, chưa phải bằng chứng đạt Accuracy 70–80% hoặc giảm thiếu hàng ở cửa hàng thực tế.

Gợi ý nhập vận hành tính theo từng SKU, lịch sử bán của cửa hàng, tồn khả dụng, thời gian giao và hàng đang về. Khách có thể chọn chuyển khoản để nhân viên đối chiếu rồi xác nhận. VNPAY chỉ hoạt động khi có cấu hình thương nhân, HTTPS và IPN hợp lệ; bộ nộp không chứa khóa thanh toán và không khẳng định đã phát sinh giao dịch ngân hàng thật.

Nguồn ảnh được lưu trong `Ma_nguon/web/store/data/photos.json` và `docs/photos.md`. Bộ tệp SQL CSDL, dữ liệu nguồn và báo cáo được giao riêng trong hồ sơ đồ án; kho công khai không chứa CSDL người dùng, khóa bí mật, môi trường cục bộ hay nhật ký chạy.

## Huấn luyện và giao diện dự đoán đã cập nhật ngày 24/11/2026

Phần huấn luyện được trình bày theo các bước của bài lab hồi quy và chuỗi thời gian. Mở `Ma_nguon/nghien_cuu/huan_luyen_nhu_cau.ipynb` hoặc chạy lệnh tại `Ma_nguon/web`:

```powershell
.venv/Scripts/python.exe tools/train_forecast.py --verify-reference
```

Công cụ đọc CSV trực tiếp, không cần CSDL hoặc cấu hình Django. Xem `Ma_nguon/nghien_cuu/README.md` để chọn vị trí dữ liệu, mã sản phẩm và thư mục kết quả. Website và công cụ dùng chung mã tạo mẫu, biến đổi và huấn luyện trong `store/forecast/training.py`.

Màn hình dự đoán hiển thị riêng nhu cầu dự đoán, lượng thực tế, chênh lệch, biểu đồ và bảng từng tháng; có nút tải bảng đối chiếu sản phẩm. Kỳ chưa có quan sát không được coi là bán bằng 0. Cập nhật dự đoán không ghi sổ kho hoặc tạo đơn hàng.

Kết quả chạy lại tại `Du_lieu/Ket_qua/Chay_lai_20261124`: 7.955 cặp Test và 2.929 mã dự đoán 08/2023 khớp bản đã chốt với dung sai 1e-8. MAE 4,7908; RMSE 14,0278; WAPE 55,8406%; Coverage 22,57%. Đây là xác nhận tái lập kết quả sau khi tổ chức lại mã, không phải kết quả cải thiện độ chính xác. Bộ kiểm tra website: 268 ca đạt; kiểm tra công cụ dữ liệu: 6 ca đạt. Thuật toán, kỳ nghiên cứu và cấu trúc CSDL được giữ tương thích với báo cáo và SQL đã nộp.
