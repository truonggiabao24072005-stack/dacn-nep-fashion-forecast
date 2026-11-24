-- Chi doc du lieu. Moi dong tra ve ten phep kiem tra va so ban ghi vi pham.
-- Ket qua 0 chi co nghia la phep doi chieu tuong ung khong tim thay vi pham.
SELECT 'so_du_khop_so_kho' AS kiem_tra, count(*)::bigint AS so_loi
FROM store_stockbalance b
LEFT JOIN (SELECT variant_id,sum(delta) AS quantity FROM store_stockentry GROUP BY variant_id) e ON e.variant_id=b.variant_id
WHERE b.quantity<>coalesce(e.quantity,0)
UNION ALL
SELECT 'bien_the_thieu_so_du',count(*) FROM store_variant v LEFT JOIN store_stockbalance b ON b.variant_id=v.id WHERE b.variant_id IS NULL
UNION ALL
SELECT 'tong_don_ban',count(*) FROM store_saleorder s LEFT JOIN
  (SELECT sale_id,sum(quantity::numeric*unit_price) total FROM store_saleline GROUP BY sale_id) l ON l.sale_id=s.id
WHERE s.total_amount<>coalesce(l.total,0)
UNION ALL
SELECT 'tong_phieu_nhap',count(*) FROM store_goodsreceipt r LEFT JOIN
  (SELECT receipt_id,sum(quantity::numeric*unit_cost) total FROM store_receiptline GROUP BY receipt_id) l ON l.receipt_id=r.id
WHERE r.total_amount<>coalesce(l.total,0)
UNION ALL
SELECT 'thanh_toan_va_don_ban',count(*) FROM store_saleorder s LEFT JOIN store_salepayment p ON p.sale_id=s.id
WHERE (s.status='POSTED' AND (p.id IS NULL OR p.amount<>s.total_amount)) OR (s.status<>'POSTED' AND p.id IS NOT NULL)
UNION ALL
SELECT 'tong_yeu_cau_web',count(*) FROM store_weborder o LEFT JOIN
  (SELECT order_id,sum(quantity::numeric*unit_price) total FROM store_weborderline GROUP BY order_id) l ON l.order_id=o.id
WHERE o.total_amount<>coalesce(l.total,0)
UNION ALL
SELECT 'luong_thang_duong_am_rong',count(*) FROM store_monthlysales
WHERE positive_qty-negative_qty_abs<>net_qty OR positive_qty='NaN'::numeric OR negative_qty_abs='NaN'::numeric OR net_qty='NaN'::numeric
UNION ALL
SELECT 'du_bao_dung_bo_du_lieu',count(*) FROM store_forecastvalue v
JOIN store_forecastunit u ON u.id=v.forecast_unit_id JOIN store_forecastrun r ON r.id=v.run_id
JOIN store_modelresult m ON m.id=r.model_result_id JOIN store_experiment x ON x.id=m.experiment_id
WHERE u.dataset_version_id<>x.dataset_version_id
UNION ALL
SELECT 'du_bao_hop_le_co_gia_tri',count(*) FROM store_forecastvalue
WHERE result_status='VALID' AND (nonnegative_value IS NULL OR nonnegative_value<0 OR nonnegative_value>='100000000000000'::numeric)
UNION ALL
SELECT 'ky_du_bao_ke_tiep',count(*) FROM store_forecastrun
WHERE target_month<>(cutoff_month+interval '1 month')::date OR extract(day FROM cutoff_month)<>1
UNION ALL
SELECT 'but_toan_co_mot_chung_tu',count(*) FROM store_stockposting p
LEFT JOIN store_saleorder s ON s.stock_posting_id=p.id
LEFT JOIN store_goodsreceipt r ON r.stock_posting_id=p.id
LEFT JOIN store_stockadjustment a ON a.stock_posting_id=p.id
LEFT JOIN store_documentcorrection c ON c.stock_posting_id=p.id
WHERE (s.id IS NOT NULL)::int+(r.id IS NOT NULL)::int+(a.id IS NOT NULL)::int+(c.id IS NOT NULL)::int<>1;
