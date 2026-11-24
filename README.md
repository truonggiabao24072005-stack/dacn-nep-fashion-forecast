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

3. Điền chuỗi vừa tạo vào `DJANGO_SECRET_KEY` của `.env`. Điền `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` theo PostgreSQL trên máy nhận. Để chạy cục bộ, đặt `DJANGO_DEBUG=true`, giữ host `127.0.0.1,localhost`. Không đăng `.env` lên GitHub.
4. Trong pgAdmin, tạo tài khoản và một CSDL mới do tài khoản đó sở hữu. Phục hồi `CSDL/du_lieu_website_20261121.dump` từ bộ hồ sơ nộp, bỏ phục hồi owner và privileges. Hoặc dùng:

```powershell
pg_restore --exit-on-error --no-owner --no-acl -h 127.0.0.1 -p 5432 -U TEN_TAI_KHOAN -d TEN_CSDL_MOI DUONG_DAN_TOI_FILE_DUMP
```

5. Đặt thư mục `Du_lieu` từ bộ hồ sơ nộp cạnh `Ma_nguon`. Có thể dùng biến `DACN_DATA_DIR` trong `.env` để chọn vị trí khác. Chạy:

```powershell
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py collectstatic --noinput
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8891
```

Trang mua hàng: http://127.0.0.1:8891/. Trang quản lý: http://127.0.0.1:8891/quan-tri/. Đăng nhập quản lý bằng tài khoản vừa tạo. Bản sao CSDL không có mật khẩu rõ; không dùng tài khoản cũ làm tài khoản mặc định trên máy khác.

Nếu cài từ CSDL rỗng, xem `manage.py help khoi_tao_cua_hang` để khởi tạo danh mục; dữ liệu nghiên cứu và lịch sử giao dịch cần nạp riêng. Luồng phục hồi bản sao là cách tái hiện đầy đủ bộ hồ sơ đã nộp.

## Kiểm tra và nghiên cứu

```powershell
.venv/Scripts/python.exe manage.py test store.tests
.venv/Scripts/python.exe -m pip install -r ../nghien_cuu/requirements.txt
.venv/Scripts/python.exe ../nghien_cuu/train.py --help
```

Kiểm thử dùng CSDL riêng; tài khoản PostgreSQL cần quyền tạo CSDL kiểm thử. Hướng dẫn nghiệp vụ ở `Ma_nguon/web/docs/usage.md`, thanh toán ở `docs/payments.md`, quản lý CSDL ở `sql/README.md`.

## Phạm vi kết quả

Danh mục bán hàng có 51 mã được đối chiếu với SKU nguồn. Nghiên cứu dùng lịch sử 2022–2023, tách Training, Validation và Test theo thời gian. Random Forest trên 7.955 cặp Test có MAE 4,7908; RMSE 14,0278; WAPE 55,8406%; Coverage 22,57%. Đây là kết quả nghiên cứu lịch sử, chưa phải bằng chứng đạt Accuracy 70–80% hoặc giảm thiếu hàng ở cửa hàng thực tế.

Gợi ý nhập vận hành tính theo từng SKU, lịch sử bán của cửa hàng, tồn khả dụng, thời gian giao và hàng đang về. Khách có thể chọn chuyển khoản để nhân viên đối chiếu rồi xác nhận. VNPAY chỉ hoạt động khi có cấu hình thương nhân, HTTPS và IPN hợp lệ; bộ nộp không chứa khóa thanh toán và không khẳng định đã phát sinh giao dịch ngân hàng thật.

Nguồn ảnh được lưu trong `Ma_nguon/web/store/data/photos.json` và `docs/photos.md`. Bản sao CSDL, dữ liệu nguồn và báo cáo được giao riêng trong hồ sơ đồ án; kho công khai không chứa CSDL người dùng, khóa bí mật, môi trường cục bộ hay nhật ký chạy.
