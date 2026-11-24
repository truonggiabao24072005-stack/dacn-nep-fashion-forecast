# Dữ liệu của đồ án

Nguồn nghiên cứu: sales_and_inventory_snapshot_data, tác giả tài khoản `tienanh2003` trên Kaggle: https://www.kaggle.com/datasets/tienanh2003/sales-and-inventory-snapshot-data.

Bộ hồ sơ nộp có đầy đủ các thư mục sau. Chép chúng vào `Du_lieu` cạnh `Ma_nguon` sau khi tải mã từ GitHub:

- `Nguon`: 37 tệp Excel nguồn; lịch sử bán hàng và danh mục dùng trong nghiên cứu nằm trong bộ này. Các bảng bổ sung được giữ để đối chiếu, không mặc nhiên dùng tất cả làm đặc trưng.
- `Huan_luyen`: tập Training, bảng đặc trưng, hợp đồng dữ liệu và kết quả rà soát chất lượng.
- `Ket_qua/Goc`: chuỗi tháng, cấu hình và kết quả các phương pháp cơ sở.
- `Ket_qua/Random_Forest`: cấu hình đã chốt, kết quả đánh giá và dự đoán được website đọc.

Mã kiểm tra và tái lập nằm trong `Ma_nguon/nghien_cuu`. Tập có bổ sung thuộc tính nguồn được lưu phục vụ đối chiếu; không đồng nghĩa toàn bộ thuộc tính đã được dùng trong Random Forest báo cáo. Không đổi ngày giao dịch, thêm số bán giả hoặc dùng Test để chọn mô hình.

Nếu vị trí dữ liệu khác, thiết lập `DACN_DATA_DIR`, `RESEARCH_RESULTS_DIR`, `RESEARCH_ARTIFACTS_DIR` trong `.env`; xem cấu hình mẫu. CSDL vận hành được nộp riêng trong `CSDL`, không phải tập huấn luyện.

`Ket_qua/Chay_lai_20261124` lưu kết quả tái lập bằng mã huấn luyện dùng chung với website, gồm CSV, JSON và biểu đồ. Hai thư mục kết quả đã chốt được giữ để đối chiếu. Công cụ mặc định tạo lần chạy mới trong `Ma_nguon/nghien_cuu/ket_qua_chay_lai`.
