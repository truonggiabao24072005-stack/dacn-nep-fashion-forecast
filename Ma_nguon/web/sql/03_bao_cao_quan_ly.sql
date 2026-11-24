BEGIN READ ONLY;
SET LOCAL TIME ZONE 'Asia/Ho_Chi_Minh';
-- San pham, co/mau, ton ban duoc va doi chieu so kho.
SELECT * FROM public.v_nep_ton_kho ORDER BY ma_san_pham,kich_co,mau;
-- Nhung bien the dang ban da cham nguong canh bao co cau hinh.
SELECT * FROM public.v_nep_ton_kho
WHERE dang_ban AND nguong_canh_bao IS NOT NULL AND ton_hien_tai<=nguong_canh_bao ORDER BY ton_hien_tai,sku;
-- Moi don chi mot dong; khong nhan tong don voi so dong hang.
SELECT * FROM public.v_nep_don_ban ORDER BY don_ban_id DESC LIMIT 100;
-- Ban goc duong, sua sai am; tach theo ngay ghi so tai Viet Nam.
SELECT ngay_ghi_so,sum(gia_tri) AS doanh_thu_sau_dieu_chinh,sum(so_luong) AS luong_sau_dieu_chinh
FROM public.v_nep_su_kien_doanh_thu GROUP BY ngay_ghi_so ORDER BY ngay_ghi_so DESC;
SELECT * FROM public.v_nep_so_kho ORDER BY dong_so_id DESC LIMIT 100;
-- Trang thai thuc hien duoc PostgreSQL suy ra tu yeu cau, don ban va chung tu bu tru.
SELECT * FROM public.v_nep_yeu_cau_web ORDER BY ma_yeu_cau DESC LIMIT 100;
-- Du lieu nghien cuu va van hanh duoc ghi ro, khong tron voi nhau.
SELECT loai_nguon,thang_chot,thang_du_bao,phuong_phap,trang_thai_ket_qua,count(*) AS so_ma
FROM public.v_nep_du_bao GROUP BY loai_nguon,thang_chot,thang_du_bao,phuong_phap,trang_thai_ket_qua
ORDER BY thang_du_bao DESC;
COMMIT;
