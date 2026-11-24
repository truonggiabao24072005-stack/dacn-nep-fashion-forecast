"""Database guards also protect writes made outside Django's forms/services."""
from django.db import migrations

SQL=r"""
CREATE FUNCTION public.nep_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_immutable_history',
  MESSAGE='Lich su da ghi so khong duoc sua hoac xoa. Su dung chung tu bu tru.';
END $$;

CREATE FUNCTION public.nep_doc_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF OLD.status='POSTED' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_posted_document_immutable',MESSAGE='Chung tu da ghi so phai duoc giu nguyen.';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.nep_line_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE parent_table text;old_id bigint;new_id bigint;state text;
BEGIN
 IF TG_TABLE_NAME='store_saleline' THEN
  parent_table='store_saleorder';
  IF TG_OP<>'INSERT' THEN old_id=OLD.sale_id; END IF;
  IF TG_OP<>'DELETE' THEN new_id=NEW.sale_id; END IF;
 ELSIF TG_TABLE_NAME='store_receiptline' THEN
  parent_table='store_goodsreceipt';
  IF TG_OP<>'INSERT' THEN old_id=OLD.receipt_id; END IF;
  IF TG_OP<>'DELETE' THEN new_id=NEW.receipt_id; END IF;
 ELSE
  parent_table='store_stockadjustment';
  IF TG_OP<>'INSERT' THEN old_id=OLD.adjustment_id; END IF;
  IF TG_OP<>'DELETE' THEN new_id=NEW.adjustment_id; END IF;
 END IF;
 FOR state IN EXECUTE format('SELECT status FROM public.%I WHERE id=ANY($1) ORDER BY id FOR UPDATE',parent_table) USING ARRAY[old_id,new_id]
 LOOP
  IF state='POSTED' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_posted_lines_immutable',MESSAGE='Khong duoc thay doi dong hang cua chung tu da ghi so.'; END IF;
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.nep_variant_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF (NEW.sku,NEW.product_id,NEW.size_id,NEW.color_id) IS DISTINCT FROM (OLD.sku,OLD.product_id,OLD.size_id,OLD.color_id)
 AND (EXISTS(SELECT 1 FROM public.store_stockentry WHERE variant_id=OLD.id)
 OR EXISTS(SELECT 1 FROM public.store_saleline WHERE variant_id=OLD.id)
 OR EXISTS(SELECT 1 FROM public.store_receiptline WHERE variant_id=OLD.id)
 OR EXISTS(SELECT 1 FROM public.store_adjustmentline WHERE variant_id=OLD.id)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_used_variant_identity',MESSAGE='Bien the da duoc tham chieu; khong doi ma, san pham, co hoac mau.';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.nep_product_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.unit IS DISTINCT FROM OLD.unit AND EXISTS(SELECT 1 FROM public.store_variant v JOIN public.store_stockentry e ON e.variant_id=v.id WHERE v.product_id=OLD.id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_used_product_unit',MESSAGE='San pham da co so kho; khong doi don vi dem.';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.nep_balance_check() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE vid bigint;balance bigint;ledger numeric;
BEGIN
 IF TG_TABLE_NAME='store_variant' THEN vid=NEW.id;
 ELSIF TG_OP='DELETE' THEN vid=OLD.variant_id;
 ELSE vid=NEW.variant_id; END IF;
 SELECT quantity INTO balance FROM public.store_stockbalance WHERE variant_id=vid FOR UPDATE;
 IF NOT FOUND THEN
  IF EXISTS(SELECT 1 FROM public.store_variant WHERE id=vid) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_variant_has_balance',MESSAGE='Moi bien the phai co mot so du kho.';
  END IF;
  RETURN NULL;
 END IF;
 SELECT coalesce(sum(delta),0) INTO ledger FROM public.store_stockentry WHERE variant_id=vid;
 IF balance<>ledger THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_balance_reconciles',MESSAGE='So du kho khong khop tong but toan. Khong sua rieng so du.';
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.nep_assert_posting(pid bigint) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE posting record;document record;documents bigint;expected jsonb;actual jsonb;expected_kind text;expected_key text;
BEGIN
 IF pid IS NULL THEN RETURN; END IF;
 SELECT * INTO posting FROM public.store_stockposting WHERE id=pid;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT count(*) INTO documents FROM (
  SELECT id FROM public.store_saleorder WHERE stock_posting_id=pid UNION ALL
  SELECT id FROM public.store_goodsreceipt WHERE stock_posting_id=pid UNION ALL
  SELECT id FROM public.store_stockadjustment WHERE stock_posting_id=pid UNION ALL
  SELECT id FROM public.store_documentcorrection WHERE stock_posting_id=pid) linked;
 IF documents<>1 THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_posting_has_document',MESSAGE='But toan kho phai thuoc dung mot chung tu.'; END IF;
 SELECT * INTO document FROM public.store_saleorder WHERE stock_posting_id=pid;
 IF FOUND THEN
  expected_kind='SALE';expected_key='SaleOrder:'||document.id;
  SELECT coalesce(jsonb_object_agg(variant_id::text,-quantity),'{}'::jsonb) INTO expected FROM public.store_saleline WHERE sale_id=document.id;
 ELSE
  SELECT * INTO document FROM public.store_goodsreceipt WHERE stock_posting_id=pid;
  IF FOUND THEN
   expected_kind='RECEIPT';expected_key='GoodsReceipt:'||document.id;
   SELECT coalesce(jsonb_object_agg(variant_id::text,quantity),'{}'::jsonb) INTO expected FROM public.store_receiptline WHERE receipt_id=document.id;
  ELSE
   SELECT * INTO document FROM public.store_stockadjustment WHERE stock_posting_id=pid;
   IF FOUND THEN
    expected_kind=CASE WHEN document.kind='OPENING' THEN 'OPENING' ELSE 'ADJUSTMENT' END;expected_key='StockAdjustment:'||document.id;
    IF document.kind='OPENING' AND EXISTS(
     SELECT 1 FROM public.store_adjustmentline l WHERE l.adjustment_id=document.id AND
      (l.expected_qty<>0 OR EXISTS(SELECT 1 FROM public.store_stockentry e WHERE e.variant_id=l.variant_id AND e.posting_id<pid)
       OR (SELECT count(*) FROM public.store_adjustmentline other_line JOIN public.store_stockadjustment other_doc ON other_doc.id=other_line.adjustment_id
           WHERE other_line.variant_id=l.variant_id AND other_doc.kind='OPENING' AND other_doc.status='POSTED')>1)) THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_opening_once',MESSAGE='Chi mo ton dau ky mot lan cho bien the chua co so kho.';
    END IF;
    SELECT coalesce(jsonb_object_agg(variant_id::text,counted_qty-expected_qty),'{}'::jsonb) INTO expected FROM public.store_adjustmentline WHERE adjustment_id=document.id AND counted_qty<>expected_qty;
   ELSE
    SELECT * INTO document FROM public.store_documentcorrection WHERE stock_posting_id=pid;
    expected_kind='CORRECTION';expected_key='DocumentCorrection:'||document.id;
    IF document.original_sale_id IS NOT NULL THEN
     IF NOT document.goods_recovered_ack OR NOT document.financial_ack OR NOT EXISTS(SELECT 1 FROM public.store_saleorder WHERE id=document.original_sale_id AND status='POSTED' AND total_amount=document.amount_snapshot) THEN
      RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_correction_evidence',MESSAGE='Chung tu sua sai ban hang thieu doi soat hang va tien.';
     END IF;
     SELECT coalesce(jsonb_object_agg(variant_id::text,quantity),'{}'::jsonb) INTO expected FROM public.store_saleline WHERE sale_id=document.original_sale_id;
    ELSE
     IF NOT EXISTS(SELECT 1 FROM public.store_goodsreceipt WHERE id=document.original_receipt_id AND status='POSTED') THEN
      RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_correction_original',MESSAGE='Phieu nhap goc chua ghi so.';
     END IF;
     SELECT coalesce(jsonb_object_agg(variant_id::text,-quantity),'{}'::jsonb) INTO expected FROM public.store_receiptline WHERE receipt_id=document.original_receipt_id;
    END IF;
   END IF;
  END IF;
 END IF;
 SELECT coalesce(jsonb_object_agg(variant_id::text,delta),'{}'::jsonb) INTO actual FROM public.store_stockentry WHERE posting_id=pid;
 IF document.status<>'POSTED' OR posting.kind<>expected_kind OR posting.business_key<>expected_key OR actual<>expected THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_posting_matches_document',MESSAGE='Loai, khoa nghiep vu hoac bien dong kho khong khop chung tu.';
 END IF;
END $$;

CREATE FUNCTION public.nep_check_commit() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE did bigint;pid bigint;document record;line_count bigint;line_total numeric;paid numeric;
BEGIN
 IF TG_TABLE_NAME='store_stockposting' THEN PERFORM public.nep_assert_posting(NEW.id);RETURN NULL; END IF;
 IF TG_TABLE_NAME='store_stockentry' THEN PERFORM public.nep_assert_posting(NEW.posting_id);RETURN NULL; END IF;
 IF TG_TABLE_NAME IN ('store_saleorder','store_saleline','store_salepayment') THEN
  IF TG_TABLE_NAME='store_saleorder' THEN did=NEW.id;
  ELSIF TG_OP='DELETE' THEN did=OLD.sale_id; ELSE did=NEW.sale_id; END IF;
  SELECT * INTO document FROM public.store_saleorder WHERE id=did;
  IF NOT FOUND THEN RETURN NULL; END IF;
  SELECT count(*),coalesce(sum(quantity::numeric*unit_price),0) INTO line_count,line_total FROM public.store_saleline WHERE sale_id=did;
  SELECT amount INTO paid FROM public.store_salepayment WHERE sale_id=did;
  IF document.total_amount<>line_total OR (document.status='POSTED' AND (line_count=0 OR paid IS NULL OR paid<>line_total)) OR (document.status<>'POSTED' AND paid IS NOT NULL) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_sale_reconciles',MESSAGE='Tong dong, tong don va thanh toan khong khop trang thai don ban.';
  END IF;
 ELSIF TG_TABLE_NAME IN ('store_goodsreceipt','store_receiptline') THEN
  IF TG_TABLE_NAME='store_goodsreceipt' THEN did=NEW.id;
  ELSIF TG_OP='DELETE' THEN did=OLD.receipt_id; ELSE did=NEW.receipt_id; END IF;
  SELECT * INTO document FROM public.store_goodsreceipt WHERE id=did;
  IF NOT FOUND THEN RETURN NULL; END IF;
  SELECT count(*),coalesce(sum(quantity::numeric*unit_cost),0) INTO line_count,line_total FROM public.store_receiptline WHERE receipt_id=did;
  IF document.total_amount<>line_total OR (document.status='POSTED' AND line_count=0) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_receipt_reconciles',MESSAGE='Tong phieu nhap khong khop cac dong hang.';
  END IF;
 ELSIF TG_TABLE_NAME IN ('store_stockadjustment','store_adjustmentline') THEN
  IF TG_TABLE_NAME='store_stockadjustment' THEN did=NEW.id;
  ELSIF TG_OP='DELETE' THEN did=OLD.adjustment_id; ELSE did=NEW.adjustment_id; END IF;
  SELECT * INTO document FROM public.store_stockadjustment WHERE id=did;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF document.status='POSTED' AND NOT EXISTS(SELECT 1 FROM public.store_adjustmentline WHERE adjustment_id=did) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_adjustment_has_lines',MESSAGE='Phieu kiem dem da ghi so phai co dong hang.';
  END IF;
 ELSE
  SELECT * INTO document FROM public.store_documentcorrection WHERE id=NEW.id;
  IF NOT FOUND THEN RETURN NULL; END IF;
 END IF;
 PERFORM public.nep_assert_posting(document.stock_posting_id);
 RETURN NULL;
END $$;

CREATE FUNCTION public.nep_forecast_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_TABLE_NAME='store_forecastrun' THEN
  IF extract(day FROM NEW.cutoff_month)<>1 OR NEW.target_month<>(NEW.cutoff_month+interval '1 month')::date THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_forecast_calendar',MESSAGE='Thang du bao phai la thang ke tiep moc chot.';
  END IF;
 END IF;
 IF EXISTS(
  SELECT 1 FROM public.store_forecastvalue v JOIN public.store_forecastunit u ON u.id=v.forecast_unit_id
  JOIN public.store_forecastrun r ON r.id=v.run_id JOIN public.store_modelresult m ON m.id=r.model_result_id
  JOIN public.store_experiment x ON x.id=m.experiment_id
  WHERE u.dataset_version_id<>x.dataset_version_id AND
   ((TG_TABLE_NAME='store_forecastvalue' AND v.id=NEW.id) OR (TG_TABLE_NAME='store_forecastunit' AND u.id=NEW.id)
   OR (TG_TABLE_NAME='store_forecastrun' AND r.id=NEW.id) OR (TG_TABLE_NAME='store_modelresult' AND m.id=NEW.id)
   OR (TG_TABLE_NAME='store_experiment' AND x.id=NEW.id))) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_forecast_dataset_matches',MESSAGE='Don vi du bao va mo hinh phai cung phien ban du lieu.';
 END IF;
 RETURN NULL;
END $$;

DO $$ DECLARE t text;BEGIN
 FOREACH t IN ARRAY ARRAY['store_stockposting','store_stockentry','store_salepayment','store_auditevent'] LOOP
  EXECUTE format('CREATE TRIGGER nep_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.nep_immutable()',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['store_saleorder','store_goodsreceipt','store_stockadjustment','store_documentcorrection'] LOOP
  EXECUTE format('CREATE TRIGGER nep_doc_guard BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.nep_doc_guard()',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['store_saleline','store_receiptline','store_adjustmentline'] LOOP
  EXECUTE format('CREATE TRIGGER nep_line_guard BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.nep_line_guard()',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['store_stockbalance','store_stockentry'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER nep_balance_check AFTER INSERT OR UPDATE OR DELETE ON public.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_balance_check()',t);
 END LOOP;
 CREATE CONSTRAINT TRIGGER nep_variant_has_balance AFTER INSERT ON public.store_variant DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_balance_check();
 CREATE TRIGGER nep_variant_guard BEFORE UPDATE ON public.store_variant FOR EACH ROW EXECUTE FUNCTION public.nep_variant_guard();
 CREATE TRIGGER nep_product_guard BEFORE UPDATE ON public.store_product FOR EACH ROW EXECUTE FUNCTION public.nep_product_guard();
 FOREACH t IN ARRAY ARRAY['store_stockposting','store_stockentry','store_saleorder','store_saleline','store_salepayment','store_goodsreceipt','store_receiptline','store_stockadjustment','store_adjustmentline','store_documentcorrection'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR UPDATE OR DELETE ON public.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit()',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['store_forecastvalue','store_forecastunit','store_forecastrun','store_modelresult','store_experiment'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER nep_forecast_guard AFTER INSERT OR UPDATE ON public.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_forecast_guard()',t);
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.nep_immutable(),public.nep_doc_guard(),public.nep_line_guard(),public.nep_variant_guard(),public.nep_product_guard(),public.nep_balance_check(),public.nep_assert_posting(bigint),public.nep_check_commit(),public.nep_forecast_guard() FROM PUBLIC;
"""

REVERSE=r"""
DROP FUNCTION public.nep_forecast_guard() CASCADE;
DROP FUNCTION public.nep_check_commit() CASCADE;
DROP FUNCTION public.nep_balance_check() CASCADE;
DROP FUNCTION public.nep_variant_guard() CASCADE;
DROP FUNCTION public.nep_product_guard() CASCADE;
DROP FUNCTION public.nep_line_guard() CASCADE;
DROP FUNCTION public.nep_doc_guard() CASCADE;
DROP FUNCTION public.nep_immutable() CASCADE;
DROP FUNCTION public.nep_assert_posting(bigint);
"""


class Migration(migrations.Migration):
    dependencies=[('store','0006_sql_numeric_integrity')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
