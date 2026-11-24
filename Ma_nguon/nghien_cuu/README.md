# Nghiên cứu nhu cầu

Mục đích chỉnh sửa là trình bày mã theo các bước giống bài lab. Giữ nguyên dữ liệu nguồn, quy tắc tạo mẫu, mốc chia tập, bốn phương pháp và tham số đã chốt; không lọc thêm hoặc điều chỉnh dữ liệu để đổi kết quả.

Cài thư viện bằng `python -m pip install -r requirements.txt`. Huấn luyện đọc CSV trực tiếp, không cần cấu hình Django, `.env` hoặc kết nối PostgreSQL.

Chạy tại `Ma_nguon/web`:

```powershell
.venv/Scripts/python.exe tools/train_forecast.py --verify-reference
```

Hoặc chạy `python train.py --verify-reference` tại thư mục nghiên cứu. Mặc định đọc `Du_lieu` cạnh `Ma_nguon`. Nếu đặt dữ liệu ở nơi khác, thêm `--data-dir "C:/duong_dan/Du_lieu"`.

Mở `huan_luyen_nhu_cau.ipynb` bằng Jupyter hoặc VS Code để xem từng bước: đọc dữ liệu, tạo X/y, chia kỳ, huấn luyện, đánh giá và biểu đồ. Notebook cần môi trường Python đã cài các thư viện nghiên cứu. Chỉnh `DATA_DIR` khi đặt dữ liệu khác vị trí mặc định.

- du_lieu.py: kiểm tra trùng mã–tháng, lượng bán và quan hệ lượng dương, âm, ròng; tháng thiếu giữ trống, tháng đã ghi nhận bán bằng 0 giữ 0.
- train.py: chạy lại bốn phương pháp theo cấu hình đã chốt, đối chiếu dự đoán với bộ kết quả đã lưu; ghi kết quả mới vào ket_qua_chay_lai.
- kiem_tra_du_lieu.py: đọc nguồn Excel, kiểm tra chất lượng và tạo lại các bản xuất học có thể truy vết.
- kiem_tra_nguon_bo_sung.py: rà các bảng nguồn bổ sung, không tự ghép dữ liệu ngoài kỳ nghiên cứu.
- kiem_tra_tap_train.py: đối chiếu hai tập Training, đặc trưng nguồn và quy tắc thời gian.
- thuc_nghiem_goc.py: giữ phương pháp của thực nghiệm ban đầu; kết quả chạy mới ghi riêng.

Đầu vào nằm trong ../../Du_lieu. Kết quả đã chốt nằm trong Ket_qua/Goc và Ket_qua/Random_Forest. Các hàm dự báo được dùng trên website nằm trong ../web/store/forecast.
Website và công cụ dùng chung `web/store/forecast/training.py`: ba tháng trễ, trung bình ba tháng, tháng trong năm; Pipeline gắn phép biến đổi đầu vào với mô hình. Mỗi kỳ chỉ dùng lịch sử trước tháng đích. Validation: 01–03/2023; Test: 04–07/2023; dự đoán tiếp: 08/2023. Giữ cấu hình đã chọn theo Validation MAE. Mã đủ sáu cặp học và ba tháng gần nhất liên tục mới được dự đoán.

Lần chạy mới xuất `predictions.csv`, `metrics.csv`, `results.json` và biểu đồ `du_bao_<ma>.png`. Có thể chọn `--output-dir` mới và `--product MH00381`. Công cụ từ chối ghi vào thư mục dữ liệu hoặc ghi đè lần chạy cũ. `--verify-reference` đối chiếu từng dự đoán Test và kỳ tiếp theo, sai lệch tối đa `1e-8`. JSON ghi cấu hình và mã băm dữ liệu, mã chạy. Kỳ chưa có thực tế không tính sai số.

Cách tổ chức tham khảo các notebook sinh viên cung cấp: `lap04` (hồi quy), `lap05` (cửa sổ quá khứ, thứ tự thời gian), `lap06` (Pipeline). Không áp dụng chia ngẫu nhiên hoặc Accuracy phân loại cho lượng bán. Tài liệu: [Pipeline](https://scikit-learn.org/1.7/modules/generated/sklearn.pipeline.Pipeline.html), [tránh rò rỉ dữ liệu](https://scikit-learn.org/1.7/common_pitfalls.html).

Dữ liệu 2022–2023 chỉ phục vụ nghiên cứu lịch sử. Bộ Test đã được xem ở các lần trước; thử cấu hình mới phải ghi là phân tích tiếp, không gọi là đánh giá độc lập mới. Kết quả hiện có chưa chứng minh đạt độ chính xác 70–80% ở cửa hàng thực tế.

Kiểm tra dữ liệu đầu vào: `python -m unittest test_du_lieu -v`. Các công cụ xuất nguồn khác giữ nguyên phạm vi; không thêm giao dịch hoặc bù lượng bán giả để làm đẹp kết quả.
