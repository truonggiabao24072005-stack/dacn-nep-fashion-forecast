# Nghiên cứu nhu cầu

Cài môi trường của website rồi cài thêm requirements.txt ở đây. Cấu hình .env trong ../web để Django nạp được CSDL.

- train.py: chạy lại bốn phương pháp theo cấu hình đã chốt, đối chiếu dự đoán với bộ kết quả đã lưu; ghi kết quả chạy lại vào ket_qua_chay_lai.
- kiem_tra_du_lieu.py: đọc nguồn Excel, kiểm tra chất lượng và tạo lại các bản xuất học có thể truy vết.
- kiem_tra_nguon_bo_sung.py: rà các bảng nguồn bổ sung, không tự ghép dữ liệu ngoài kỳ nghiên cứu.
- kiem_tra_tap_train.py: đối chiếu hai tập Training, đặc trưng nguồn và quy tắc thời gian.
- thuc_nghiem_goc.py: giữ phương pháp của thực nghiệm ban đầu; kết quả chạy mới ghi riêng.

Đầu vào nằm trong ../../Du_lieu. Kết quả đã chốt nằm trong Ket_qua/Goc và Ket_qua/Random_Forest. Các hàm dự báo được dùng trên website nằm trong ../web/store/forecast.
Chỉ chạy các lệnh xuất lại dữ liệu khi muốn tái tạo bản xuất. Lần sắp xếp mã không thêm giao dịch, không thay bộ Train và không huấn luyện lại mô hình để đổi số liệu.
