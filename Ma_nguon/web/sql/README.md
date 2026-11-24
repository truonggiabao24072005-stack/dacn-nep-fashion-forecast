# Quản lý PostgreSQL

Ứng dụng dùng các migration từ 0001 đến 0019. Lược đồ `00_luoc_do.sql` được xuất từ bản sao CSDL hiện hành. Các truy vấn chỉ đọc để kiểm tra và báo cáo nằm cạnh tệp này.

| Tệp | Mục đích |
|---|---|
| 00_luoc_do.sql | Cấu trúc bảng, chỉ mục, ràng buộc, hàm và trigger |
| 01_xem_cau_truc.sql | Xem các đối tượng CSDL |
| 02_kiem_tra_toan_ven.sql | Đối chiếu chứng từ, khoản thu, dự báo và sổ kho |
| 03_bao_cao_quan_ly.sql | Truy vấn báo cáo chỉ đọc |
| 04_phan_quyen_trien_khai.psql | Mẫu phân quyền để cấu hình theo môi trường |

## Lệnh sử dụng

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
Mẫu phân quyền không phải bằng chứng các vai trò đã được triển khai. Khi chuyển máy, tạo tài khoản và CSDL mới, dùng pg_restore với --no-owner và --no-acl theo hướng dẫn bàn giao.
Trạng thái chứng từ, khoản thu và biến động kho do dịch vụ cùng ràng buộc PostgreSQL kiểm soát. Không sửa số dư hoặc trạng thái bằng truy vấn ghi trực tiếp để thay thao tác nghiệp vụ.
