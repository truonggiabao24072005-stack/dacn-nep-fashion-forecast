# Ảnh và danh mục

Ảnh phục vụ website nằm trong static/shop/images. Tệp `store/data/photos.json` ghi đường dẫn, nguồn ảnh, dung lượng và SHA-256; `store/data/products.json` lưu đối chiếu danh mục. Các đợt bổ sung ở `store/data/collections/`.
Ảnh tham khảo được chọn theo loại hàng, màu và đối tượng; nguồn nghiên cứu không cung cấp ảnh gắn trực tiếp với từng SKU. Giá và tồn hiển thị được đọc từ CSDL, không suy ra từ ảnh.
Dùng `python tools/audit_files.py` sau khi chạy collectstatic để kiểm tra ảnh và các tệp được tham chiếu trong giao diện.
