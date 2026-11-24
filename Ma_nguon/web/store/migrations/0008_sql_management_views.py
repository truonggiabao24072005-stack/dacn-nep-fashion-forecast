from django.db import migrations

SQL=r"""
CREATE VIEW public.v_nep_ton_kho AS
WITH ledger AS (SELECT variant_id,sum(delta) quantity FROM public.store_stockentry GROUP BY variant_id)
SELECT v.id AS bien_the_id,p.code AS ma_san_pham,p.name AS ten_san_pham,v.sku,
 sz.name AS kich_co,cl.name AS mau,p.unit AS don_vi,v.selling_price AS gia_ban,
 b.quantity AS ton_hien_tai,coalesce(l.quantity,0) AS ton_so_kho,b.quantity-coalesce(l.quantity,0) AS chenh_lech,
 (v.is_active AND p.is_active AND c.is_active AND br.is_active AND sz.is_active AND cl.is_active AND v.selling_price>0) AS dang_ban,
 CASE WHEN v.is_active AND p.is_active AND c.is_active AND br.is_active AND sz.is_active AND cl.is_active AND v.selling_price>0 THEN b.quantity ELSE 0 END AS ton_ban_duoc,
 v.low_stock_threshold AS nguong_canh_bao,b.version AS phien_ban_ton,b.updated_at AS cap_nhat_luc
FROM public.store_variant v JOIN public.store_product p ON p.id=v.product_id
JOIN public.store_category c ON c.id=p.category_id JOIN public.store_brand br ON br.id=p.brand_id
JOIN public.store_size sz ON sz.id=v.size_id JOIN public.store_color cl ON cl.id=v.color_id
JOIN public.store_stockbalance b ON b.variant_id=v.id LEFT JOIN ledger l ON l.variant_id=v.id;

CREATE VIEW public.v_nep_don_ban AS
WITH lines AS (SELECT sale_id,count(*) so_dong,sum(quantity) so_luong,sum(quantity::numeric*unit_price) tong_dong FROM public.store_saleline GROUP BY sale_id)
SELECT s.id AS don_ban_id,s.code AS ma_don,s.status AS trang_thai,s.created_by_id AS nguoi_lap_id,
 s.posted_at AS ghi_so_luc,(s.posted_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS ngay_ghi_so,
 coalesce(l.so_dong,0) AS so_dong,coalesce(l.so_luong,0) AS so_luong,s.total_amount AS tong_don,
 coalesce(l.tong_dong,0) AS tong_dong,p.method AS phuong_thuc,p.amount AS tien_da_ghi_nhan,
 s.total_amount-coalesce(l.tong_dong,0) AS chenh_lech
FROM public.store_saleorder s LEFT JOIN lines l ON l.sale_id=s.id LEFT JOIN public.store_salepayment p ON p.sale_id=s.id;

CREATE VIEW public.v_nep_so_kho AS
SELECT e.id AS dong_so_id,v.sku,p.code AS ma_san_pham,sz.name AS kich_co,cl.name AS mau,
 sp.kind AS loai_bien_dong,sp.business_key AS khoa_chung_tu,e.delta AS thay_doi,
 sp.posted_at AS ghi_so_luc,sp.posted_by_id AS nguoi_ghi_so_id
FROM public.store_stockentry e JOIN public.store_stockposting sp ON sp.id=e.posting_id
JOIN public.store_variant v ON v.id=e.variant_id JOIN public.store_product p ON p.id=v.product_id
JOIN public.store_size sz ON sz.id=v.size_id JOIN public.store_color cl ON cl.id=v.color_id;

CREATE VIEW public.v_nep_du_bao AS
SELECT v.id AS ket_qua_id,d.code AS phien_ban_du_lieu,d.source_type AS loai_nguon,
 d.status AS trang_thai_du_lieu,u.external_key AS ma_nguon,u.label AS ten_hien_thi,
 u.granularity AS cap_du_bao,u.unit AS don_vi,u.scope_key AS pham_vi,u.mapping_status AS anh_xa,
 p.code AS ma_san_pham_noi_bo,r.cutoff_month AS thang_chot,r.target_month AS thang_du_bao,
 m.method AS phuong_phap,m.selected_on_validation AS da_chon_bang_kiem_dinh,r.status AS trang_thai_chay,
 v.nonnegative_value AS luong_du_bao,v.result_status AS trang_thai_ket_qua,
 m.validation_metrics AS sai_so_kiem_dinh,m.test_metrics AS sai_so_kiem_tra
FROM public.store_forecastvalue v JOIN public.store_forecastunit u ON u.id=v.forecast_unit_id
LEFT JOIN public.store_product p ON p.id=u.internal_product_id JOIN public.store_forecastrun r ON r.id=v.run_id
JOIN public.store_modelresult m ON m.id=r.model_result_id JOIN public.store_experiment x ON x.id=m.experiment_id
JOIN public.store_datasetversion d ON d.id=x.dataset_version_id;

CREATE VIEW public.v_nep_su_kien_doanh_thu AS
WITH quantities AS (SELECT sale_id,sum(quantity) quantity FROM public.store_saleline GROUP BY sale_id)
SELECT 'SALE'::text AS loai,s.id AS chung_tu_id,s.code AS ma_chung_tu,s.code AS ma_goc,s.posted_at AS ghi_so_luc,
 (s.posted_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS ngay_ghi_so,s.total_amount AS gia_tri,coalesce(q.quantity,0) AS so_luong
FROM public.store_saleorder s LEFT JOIN quantities q ON q.sale_id=s.id WHERE s.status='POSTED'
UNION ALL
SELECT 'CORRECTION',c.id,c.code,s.code,c.posted_at,(c.posted_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date,
 -c.amount_snapshot,-coalesce(q.quantity,0)
FROM public.store_documentcorrection c JOIN public.store_saleorder s ON s.id=c.original_sale_id
LEFT JOIN quantities q ON q.sale_id=s.id WHERE c.status='POSTED';
"""


class Migration(migrations.Migration):
    dependencies=[('store','0007_sql_business_guards')]
    operations=[migrations.RunSQL(SQL,';'.join('DROP VIEW public.'+name for name in [
        'v_nep_su_kien_doanh_thu','v_nep_du_bao','v_nep_so_kho','v_nep_don_ban','v_nep_ton_kho'])+';')]
