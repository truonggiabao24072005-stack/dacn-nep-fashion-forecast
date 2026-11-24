# Quản lý PostgreSQL

Ứng dụng dùng các migration từ 0001 đến 0019. Lược đồ `00_luoc_do.sql` được xuất từ CSDL hiện hành. Các truy vấn chỉ đọc để kiểm tra và báo cáo nằm cạnh tệp này.

| Tệp | Mục đích |
|---|---|
| 00_luoc_do.sql | Cấu trúc bảng, chỉ mục, ràng buộc, hàm và trigger |
| 01_xem_cau_truc.sql | Xem các đối tượng CSDL |
| 02_kiem_tra_toan_ven.sql | Đối chiếu chứng từ, khoản thu, dự báo và sổ kho |
| 03_bao_cao_quan_ly.sql | Truy vấn báo cáo chỉ đọc |
| 04_phan_quyen_trien_khai.psql | Mẫu phân quyền để cấu hình theo môi trường |

## Tạo cơ sở dữ liệu để chấm đồ án

Bộ nộp dùng SQL thuần trong thư mục `CSDL` ở gốc hồ sơ:

1. Trong pgAdmin, mở Query Tool tại `postgres`, bật Auto commit, chạy riêng `00_tao_database.sql`.
2. Refresh mục Databases, chọn database `dacn_truong_gia_bao` vừa tạo, mở Query Tool mới, bật Auto commit và chạy toàn bộ `01_khoi_tao_he_thong.sql` để tạo cấu trúc và nạp dữ liệu.
3. Chạy `02_kiem_tra_sau_khi_chay.sql` để đối chiếu. Hướng dẫn chi tiết nằm trong `HUONG_DAN_CHAY_POSTGRESQL.txt` cạnh các tệp SQL.

Bộ SQL chứa đầy đủ khóa, chỉ mục, hàm, trigger và dữ liệu đã đối chiếu. Không cần chạy công cụ quản trị Python hoặc dùng Restore để nạp bộ này. Tệp `00_luoc_do.sql` trong mã nguồn là lược đồ tham khảo; không thay thế bộ SQL đầy đủ trong `CSDL`.

## Lệnh quản trị khi đã chạy ứng dụng

Từ thư mục website, dùng Python của môi trường:

```powershell
python tools/manage_database.py query --report cau-truc
python tools/manage_database.py query --report kiem-tra
python tools/manage_database.py query --report bao-cao
python tools/manage_database.py backup
python tools/manage_database.py verify --dump DUONG_DAN_BAN_SAO.dump
python tools/manage_database.py export-schema
```

Lệnh backup chụp bản sao nhất quán và lưu dấu dữ liệu của từng bảng. Lệnh verify phục hồi vào CSDL kiểm tra có tên riêng, đối chiếu rồi dọn CSDL đó; không phục hồi đè CSDL đang dùng. Kết quả được ghi trong `.runtime/evidence/sql_20261025/`.
Mẫu phân quyền không phải bằng chứng các vai trò đã được triển khai. Khi dùng bản sao `.dump` do công cụ quản trị tạo, phục hồi vào CSDL mới với --no-owner và --no-acl; đây là cách quản trị bổ sung, không phải bước nạp bộ SQL trong hồ sơ.
Trạng thái chứng từ, khoản thu và biến động kho do dịch vụ cùng ràng buộc PostgreSQL kiểm soát. Không sửa số dư hoặc trạng thái bằng truy vấn ghi trực tiếp để thay thao tác nghiệp vụ.
