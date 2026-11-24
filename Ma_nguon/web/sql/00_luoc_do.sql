--
-- PostgreSQL database dump
--

\restrict iwfVlPLCbOhYVS7MLiAxj9UC5Izjbt1ZddvE9MbGALxAFf98QIldsCxfmM7dnCQ

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: nep_assert_posting(bigint); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_assert_posting(pid bigint) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
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


--
-- Name: nep_balance_check(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_balance_check() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
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


--
-- Name: nep_check_commit(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_check_commit() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
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


--
-- Name: nep_check_gateway_sale(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_check_gateway_sale() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 IF EXISTS (SELECT 1 FROM public.store_weborder WHERE sale_id=NEW.sale_id AND payment_preference='VNPAY')
    OR NEW.method='VNPAY' THEN
  IF NEW.method<>'VNPAY' OR NOT EXISTS (
    SELECT 1 FROM public.store_weborder w JOIN public.store_gatewaypayment g ON g.order_id=w.id
    WHERE w.sale_id=NEW.sale_id AND w.payment_preference='VNPAY'
      AND g.status='REVIEW' AND g.amount=NEW.amount AND g.provider_reference=NEW.reference
  ) THEN
   RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='nep_gateway_sale_matches',
     MESSAGE='Khoan thu VNPAY can ket qua da doi chieu va khop so tien.';
  END IF;
 END IF;
 RETURN NEW;
END $$;


--
-- Name: nep_check_shipment(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_check_shipment() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 IF (NEW.shipment_status,NEW.tracking_number) IS DISTINCT FROM (OLD.shipment_status,OLD.tracking_number) THEN
  IF public.nep_web_lifecycle(NEW.id) IS DISTINCT FROM 'COMPLETED'
     OR NOT (
      (OLD.shipment_status='' AND NEW.shipment_status='SHIPPED') OR
      (OLD.shipment_status='SHIPPED' AND NEW.shipment_status='DELIVERED'
       AND OLD.tracking_number=NEW.tracking_number)
     ) THEN
   RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='nep_shipment_transition',
     MESSAGE='Don phai ghi so va chuyen trang thai giao hang dung thu tu.';
  END IF;
 END IF;
 RETURN NEW;
END $$;


--
-- Name: nep_check_supplier_receipt(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_check_supplier_receipt() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE planned public.store_supplierorder%ROWTYPE;
DECLARE qty numeric;
DECLARE already_received numeric;
BEGIN
 IF TG_OP='UPDATE' AND OLD.status='POSTED'
    AND NEW.supplier_order_id IS DISTINCT FROM OLD.supplier_order_id THEN
   RAISE EXCEPTION 'Khong duoc doi don dat cua phieu da ghi so' USING ERRCODE='23514';
 END IF;
 IF NEW.supplier_order_id IS NULL OR NEW.status <> 'POSTED' THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND OLD.status='POSTED' THEN RETURN NEW; END IF;
 SELECT * INTO planned FROM public.store_supplierorder WHERE id=NEW.supplier_order_id FOR UPDATE;
 IF NOT FOUND OR planned.cancelled_at IS NOT NULL OR planned.supplier_id <> NEW.supplier_id THEN
   RAISE EXCEPTION 'Don dat hoac nha cung cap khong khop' USING ERRCODE='23514';
 END IF;
 SELECT sum(quantity) INTO qty FROM public.store_receiptline WHERE receipt_id=NEW.id AND variant_id=planned.variant_id;
 IF qty IS NULL OR EXISTS(SELECT 1 FROM public.store_receiptline WHERE receipt_id=NEW.id AND variant_id<>planned.variant_id) THEN
   RAISE EXCEPTION 'Bien the nhap khong khop don dat' USING ERRCODE='23514';
 END IF;
 SELECT coalesce(sum(l.quantity),0) INTO already_received
 FROM public.store_receiptline l JOIN public.store_goodsreceipt r ON r.id=l.receipt_id
 WHERE r.supplier_order_id=planned.id AND r.status='POSTED'
   AND NOT EXISTS(SELECT 1 FROM public.store_documentcorrection c WHERE c.original_receipt_id=r.id AND c.status='POSTED');
 IF qty + already_received > planned.ordered_qty THEN
   RAISE EXCEPTION 'So luong nhap vuot don dat' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;


--
-- Name: nep_doc_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_doc_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.status<>'DRAFT' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_document_initial_state',MESSAGE='Chung tu phai duoc lap o trang thai nhap.';
  END IF;
  RETURN NEW;
 END IF;
 IF OLD.status='POSTED' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_posted_document_immutable',MESSAGE='Chung tu da ghi so phai duoc giu nguyen.';
 END IF;
 IF OLD.status='CANCELLED' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_cancelled_document_immutable',MESSAGE='Chung tu da huy khong duoc mo lai, sua hoac xoa.';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF NEW.status IS DISTINCT FROM OLD.status AND NEW.version<>OLD.version+1 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_document_transition_version',MESSAGE='Chuyen trang thai phai tang phien ban dung mot.';
 END IF;
 IF NEW.status='CANCELLED' AND length(btrim(NEW.cancel_reason))=0 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_document_cancel_reason',MESSAGE='Huy chung tu phai co ly do.';
 END IF;
 RETURN NEW;
END $$;


--
-- Name: nep_forecast_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_forecast_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
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


--
-- Name: nep_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_immutable() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_immutable_history',
  MESSAGE='Lich su da ghi so khong duoc sua hoac xoa. Su dung chung tu bu tru.';
END $$;


--
-- Name: nep_line_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_line_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $_$
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
END $_$;


--
-- Name: nep_parent_link_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_parent_link_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE old_key bigint;new_key bigint;
BEGIN
 IF TG_TABLE_NAME='store_saleline' THEN old_key=OLD.sale_id;new_key=NEW.sale_id;
 ELSIF TG_TABLE_NAME='store_receiptline' THEN old_key=OLD.receipt_id;new_key=NEW.receipt_id;
 ELSIF TG_TABLE_NAME='store_adjustmentline' THEN old_key=OLD.adjustment_id;new_key=NEW.adjustment_id;
 ELSE old_key=OLD.variant_id;new_key=NEW.variant_id; END IF;
 IF old_key IS DISTINCT FROM new_key THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_parent_link_preserved',MESSAGE='Khong chuyen dong chung tu hoac so du sang doi tuong khac.';
 END IF;
 RETURN NEW;
END $$;


--
-- Name: nep_product_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_product_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 IF NEW.unit IS DISTINCT FROM OLD.unit AND EXISTS(SELECT 1 FROM public.store_variant v JOIN public.store_stockentry e ON e.variant_id=v.id WHERE v.product_id=OLD.id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_used_product_unit',MESSAGE='San pham da co so kho; khong doi don vi dem.';
 END IF;
 RETURN NEW;
END $$;


--
-- Name: nep_variant_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_variant_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 IF (NEW.sku,NEW.product_id,NEW.size_id,NEW.color_id) IS DISTINCT FROM (OLD.sku,OLD.product_id,OLD.size_id,OLD.color_id)
 AND (EXISTS(SELECT 1 FROM public.store_stockentry WHERE variant_id=OLD.id)
 OR EXISTS(SELECT 1 FROM public.store_saleline WHERE variant_id=OLD.id)
 OR EXISTS(SELECT 1 FROM public.store_receiptline WHERE variant_id=OLD.id)
 OR EXISTS(SELECT 1 FROM public.store_adjustmentline WHERE variant_id=OLD.id)
 OR EXISTS(SELECT 1 FROM public.store_weborderline WHERE variant_id=OLD.id)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_used_variant_identity',MESSAGE='Bien the da duoc tham chieu; khong doi ma, san pham, co hoac mau.';
 END IF;
 RETURN NEW;
END $$;


--
-- Name: nep_web_check(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_web_check() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE oid uuid;amount numeric;line_total numeric;line_count bigint;
BEGIN
 IF TG_TABLE_NAME='store_weborder' THEN oid=NEW.id;
 ELSIF TG_OP='DELETE' THEN oid=OLD.order_id;
 ELSE oid=NEW.order_id; END IF;
 SELECT total_amount INTO amount FROM public.store_weborder WHERE id=oid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT count(*),coalesce(sum(quantity::numeric*unit_price),0) INTO line_count,line_total
 FROM public.store_weborderline WHERE order_id=oid;
 IF line_count NOT BETWEEN 1 AND 30 OR amount<>line_total THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_web_total_reconciles',MESSAGE='Yeu cau can 1 den 30 dong va tong tien phai khop dong hang.';
 END IF;
 RETURN NULL;
END $$;


--
-- Name: nep_web_lifecycle(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_web_lifecycle(request_id uuid) RETURNS text
    LANGUAGE sql STABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
 SELECT trang_thai_thuc_hien FROM public.v_nep_yeu_cau_web WHERE yeu_cau_id=request_id
$$;


--
-- Name: nep_web_snapshot_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_web_snapshot_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_web_request_preserved',MESSAGE='Yeu cau da gui phai duoc giu de doi chieu.';
 END IF;
 IF (NEW.id,NEW.code,NEW.request_key,NEW.owner_hash,NEW.payload_hash,NEW.customer_name,NEW.phone,NEW.note,NEW.payment_preference,NEW.delivery_address,NEW.pickup_address,NEW.pickup_address_is_example,NEW.total_amount,NEW.created_at)
 IS DISTINCT FROM (OLD.id,OLD.code,OLD.request_key,OLD.owner_hash,OLD.payload_hash,OLD.customer_name,OLD.phone,OLD.note,OLD.payment_preference,OLD.delivery_address,OLD.pickup_address,OLD.pickup_address_is_example,OLD.total_amount,OLD.created_at) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_web_snapshot_immutable',MESSAGE='Thong tin va gia tri da chot cua yeu cau khong duoc ghi lai.';
 END IF;
 RETURN NEW;
END $$;


--
-- Name: nep_web_transition_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.nep_web_transition_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE sale_state text;
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.status<>'PENDING' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_web_initial_state',MESSAGE='Yeu cau moi phai cho xac nhan.';
  END IF;
  RETURN NEW;
 END IF;
 IF (NEW.status,NEW.sale_id,NEW.handled_by_id,NEW.handled_at,NEW.reason,NEW.cancel_origin,NEW.version)
 IS NOT DISTINCT FROM (OLD.status,OLD.sale_id,OLD.handled_by_id,OLD.handled_at,OLD.reason,OLD.cancel_origin,OLD.version) THEN RETURN NEW; END IF;
 IF OLD.status<>'PENDING' OR NEW.status NOT IN ('ACCEPTED','CANCELLED') OR NEW.version<>OLD.version+1 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_web_transition_valid',MESSAGE='Chi chuyen yeu cau dang cho sang tiep nhan hoac huy; phien ban phai tang dung mot.';
 END IF;
 IF NEW.status='ACCEPTED' THEN
  SELECT status INTO sale_state FROM public.store_saleorder WHERE id=NEW.sale_id FOR UPDATE;
  IF sale_state IS DISTINCT FROM 'DRAFT' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_web_accept_draft_sale',MESSAGE='Tiep nhan phai lien ket voi don ban nhap.';
  END IF;
 END IF;
 RETURN NEW;
END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: auth_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(150) NOT NULL
);


--
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group_permissions (
    id bigint NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


--
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_permission ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


--
-- Name: store_adjustmentline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_adjustmentline (
    id bigint NOT NULL,
    expected_qty integer NOT NULL,
    expected_version integer NOT NULL,
    counted_qty integer NOT NULL,
    adjustment_id bigint NOT NULL,
    variant_id bigint NOT NULL,
    CONSTRAINT store_adjustmentline_counted_qty_check CHECK ((counted_qty >= 0)),
    CONSTRAINT store_adjustmentline_expected_qty_check CHECK ((expected_qty >= 0)),
    CONSTRAINT store_adjustmentline_expected_version_check CHECK ((expected_version >= 0))
);


--
-- Name: store_adjustmentline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_adjustmentline ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_adjustmentline_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_auditevent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_auditevent (
    id bigint NOT NULL,
    action character varying(60) NOT NULL,
    object_type character varying(60) NOT NULL,
    object_id character varying(80) NOT NULL,
    changed_fields jsonb NOT NULL,
    reason text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    actor_id bigint
);


--
-- Name: store_auditevent_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_auditevent ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_auditevent_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_brand; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_brand (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(80) NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean NOT NULL,
    version integer NOT NULL,
    CONSTRAINT store_brand_version_check CHECK ((version >= 0))
);


--
-- Name: store_brand_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_brand ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_brand_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_category; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_category (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(80) NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean NOT NULL,
    version integer NOT NULL,
    CONSTRAINT store_category_version_check CHECK ((version >= 0))
);


--
-- Name: store_category_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_category ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_category_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_color; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_color (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(80) NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean NOT NULL,
    version integer NOT NULL,
    CONSTRAINT store_color_version_check CHECK ((version >= 0))
);


--
-- Name: store_color_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_color ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_color_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_customer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_customer (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(80) NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean NOT NULL,
    version integer NOT NULL,
    phone character varying(25) NOT NULL,
    note text NOT NULL,
    CONSTRAINT store_customer_version_check CHECK ((version >= 0))
);


--
-- Name: store_customer_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_customer ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_customer_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_customerloginattempt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_customerloginattempt (
    key character varying(64) NOT NULL,
    failures integer NOT NULL,
    window_start timestamp with time zone NOT NULL,
    CONSTRAINT store_customerloginattempt_failures_check CHECK ((failures >= 0))
);


--
-- Name: store_customerprofile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_customerprofile (
    id bigint NOT NULL,
    phone character varying(25) NOT NULL,
    user_id bigint NOT NULL
);


--
-- Name: store_customerprofile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_customerprofile ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_customerprofile_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_datasetversion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_datasetversion (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(50) NOT NULL,
    source_type character varying(12) NOT NULL,
    manifest_hash character varying(64) NOT NULL,
    coverage_start date NOT NULL,
    coverage_end date NOT NULL,
    scope_definition jsonb NOT NULL,
    cleaning_config jsonb NOT NULL,
    status character varying(12) NOT NULL,
    created_by_id bigint NOT NULL
);


--
-- Name: store_datasetversion_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_datasetversion ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_datasetversion_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_documentcorrection; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_documentcorrection (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(30) NOT NULL,
    status character varying(12) NOT NULL,
    version integer NOT NULL,
    posted_at timestamp with time zone,
    cancel_reason text NOT NULL,
    reason text NOT NULL,
    evidence text NOT NULL,
    goods_recovered_ack boolean NOT NULL,
    financial_ack boolean NOT NULL,
    amount_snapshot numeric(18,0) NOT NULL,
    created_by_id bigint NOT NULL,
    posted_by_id bigint,
    original_receipt_id bigint,
    original_sale_id bigint,
    stock_posting_id bigint,
    CONSTRAINT correction_one_original CHECK ((((original_receipt_id IS NULL) AND (original_sale_id IS NOT NULL)) OR ((original_receipt_id IS NOT NULL) AND (original_sale_id IS NULL)))),
    CONSTRAINT documentcorrection_state_consistent CHECK ((((posted_at IS NOT NULL) AND (posted_by_id IS NOT NULL) AND ((status)::text = 'POSTED'::text) AND (stock_posting_id IS NOT NULL)) OR ((posted_at IS NULL) AND (posted_by_id IS NULL) AND ((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[])) AND (stock_posting_id IS NULL)))),
    CONSTRAINT store_documentcorrection_version_check CHECK ((version >= 0))
);


--
-- Name: store_documentcorrection_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_documentcorrection ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_documentcorrection_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_experiment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_experiment (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    target_definition jsonb NOT NULL,
    eligibility_policy jsonb NOT NULL,
    split_config jsonb NOT NULL,
    feature_spec jsonb NOT NULL,
    model_configs jsonb NOT NULL,
    random_seed integer NOT NULL,
    status character varying(12) NOT NULL,
    dataset_version_id bigint NOT NULL
);


--
-- Name: store_experiment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_experiment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_experiment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_externalskumap; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_externalskumap (
    id bigint NOT NULL,
    external_product_id character varying(100) NOT NULL,
    evidence text NOT NULL,
    verified_by_id bigint,
    forecast_unit_id bigint NOT NULL,
    internal_variant_id bigint
);


--
-- Name: store_externalskumap_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_externalskumap ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_externalskumap_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_forecastrun; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_forecastrun (
    id bigint NOT NULL,
    cutoff_month date NOT NULL,
    target_month date NOT NULL,
    scope_key character varying(100) NOT NULL,
    status character varying(12) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    model_result_id bigint NOT NULL
);


--
-- Name: store_forecastrun_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_forecastrun ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_forecastrun_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_forecastunit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_forecastunit (
    id bigint NOT NULL,
    external_key character varying(100) NOT NULL,
    label character varying(200) NOT NULL,
    granularity character varying(10) NOT NULL,
    unit character varying(20) NOT NULL,
    scope_key character varying(100) NOT NULL,
    mapping_status character varying(12) NOT NULL,
    mapping_evidence text NOT NULL,
    dataset_version_id bigint NOT NULL,
    internal_product_id bigint
);


--
-- Name: store_forecastunit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_forecastunit ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_forecastunit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_forecastvalue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_forecastvalue (
    id bigint NOT NULL,
    raw_value numeric(18,4),
    nonnegative_value numeric(18,4),
    result_status character varying(20) NOT NULL,
    forecast_unit_id bigint NOT NULL,
    run_id bigint NOT NULL,
    CONSTRAINT forecast_nonnegative CHECK ((((nonnegative_value >= (0)::numeric) AND (nonnegative_value < ('100000000000000'::bigint)::numeric)) OR (nonnegative_value IS NULL))),
    CONSTRAINT forecast_raw_finite CHECK (((raw_value IS NULL) OR ((raw_value > ('-100000000000000'::bigint)::numeric) AND (raw_value < ('100000000000000'::bigint)::numeric)))),
    CONSTRAINT valid_forecast_has_value CHECK (((NOT ((result_status)::text = 'VALID'::text)) OR (nonnegative_value IS NOT NULL)))
);


--
-- Name: store_forecastvalue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_forecastvalue ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_forecastvalue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_gatewaypayment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_gatewaypayment (
    id uuid NOT NULL,
    amount bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    client_ip inet NOT NULL,
    status character varying(10) NOT NULL,
    provider_reference character varying(32),
    order_id uuid NOT NULL,
    CONSTRAINT gateway_amount_vnd CHECK (((amount > 0) AND (amount < '10000000000'::bigint))),
    CONSTRAINT gateway_result_valid CHECK ((((provider_reference IS NULL) AND ((status)::text = ANY ((ARRAY['WAITING'::character varying, 'FAILED'::character varying])::text[]))) OR ((provider_reference IS NOT NULL) AND ((status)::text = ANY ((ARRAY['REVIEW'::character varying, 'POSTED'::character varying])::text[])) AND (NOT (((provider_reference)::text = ''::text) AND (provider_reference IS NOT NULL)))))),
    CONSTRAINT store_gatewaypayment_amount_check CHECK ((amount >= 0))
);


--
-- Name: store_goodsreceipt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_goodsreceipt (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(30) NOT NULL,
    status character varying(12) NOT NULL,
    version integer NOT NULL,
    posted_at timestamp with time zone,
    cancel_reason text NOT NULL,
    supplier_name_snapshot character varying(200) NOT NULL,
    delivery_reference character varying(100) NOT NULL,
    total_amount numeric(18,0) NOT NULL,
    note text NOT NULL,
    created_by_id bigint NOT NULL,
    posted_by_id bigint,
    stock_posting_id bigint,
    supplier_id bigint NOT NULL,
    supplier_order_id bigint,
    CONSTRAINT goodsreceipt_state_consistent CHECK ((((posted_at IS NOT NULL) AND (posted_by_id IS NOT NULL) AND ((status)::text = 'POSTED'::text) AND (stock_posting_id IS NOT NULL)) OR ((posted_at IS NULL) AND (posted_by_id IS NULL) AND ((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[])) AND (stock_posting_id IS NULL)))),
    CONSTRAINT receipt_total_valid CHECK (((total_amount >= (0)::numeric) AND (total_amount < ('1000000000000000000'::bigint)::numeric))),
    CONSTRAINT store_goodsreceipt_version_check CHECK ((version >= 0))
);


--
-- Name: store_goodsreceipt_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_goodsreceipt ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_goodsreceipt_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_modelresult; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_modelresult (
    id bigint NOT NULL,
    method character varying(20) NOT NULL,
    selected_on_validation boolean NOT NULL,
    validation_metrics jsonb NOT NULL,
    test_metrics jsonb NOT NULL,
    scored_pair_manifest jsonb NOT NULL,
    artifact_path text NOT NULL,
    artifact_hash character varying(64) NOT NULL,
    experiment_id bigint NOT NULL
);


--
-- Name: store_modelresult_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_modelresult ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_modelresult_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_monthlysales; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_monthlysales (
    id bigint NOT NULL,
    month date NOT NULL,
    positive_qty numeric(18,4) NOT NULL,
    negative_qty_abs numeric(18,4) NOT NULL,
    net_qty numeric(18,4) NOT NULL,
    target_qty numeric(18,4),
    observation_status character varying(15) NOT NULL,
    source_row_count integer NOT NULL,
    forecast_unit_id bigint NOT NULL,
    CONSTRAINT monthly_first_day CHECK ((EXTRACT(day FROM month) = (1)::numeric)),
    CONSTRAINT monthly_net_reconciles CHECK (((net_qty = (positive_qty - negative_qty_abs)) AND (net_qty > ('-100000000000000'::bigint)::numeric) AND (net_qty < ('100000000000000'::bigint)::numeric))),
    CONSTRAINT monthly_nonnegative_flows CHECK (((negative_qty_abs >= (0)::numeric) AND (negative_qty_abs < ('100000000000000'::bigint)::numeric) AND (positive_qty >= (0)::numeric) AND (positive_qty < ('100000000000000'::bigint)::numeric))),
    CONSTRAINT monthly_target_valid CHECK (((target_qty IS NULL) OR ((target_qty >= (0)::numeric) AND (target_qty < ('100000000000000'::bigint)::numeric)))),
    CONSTRAINT store_monthlysales_source_row_count_check CHECK ((source_row_count >= 0))
);


--
-- Name: store_monthlysales_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_monthlysales ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_monthlysales_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_operationrequest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_operationrequest (
    id bigint NOT NULL,
    operation character varying(40) NOT NULL,
    request_key uuid NOT NULL,
    payload_hash character varying(64) NOT NULL,
    result_type character varying(40) NOT NULL,
    result_id bigint NOT NULL,
    completed_at timestamp with time zone NOT NULL,
    actor_id bigint NOT NULL
);


--
-- Name: store_operationrequest_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_operationrequest ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_operationrequest_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_product; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_product (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(80) NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean NOT NULL,
    version integer NOT NULL,
    unit character varying(20) NOT NULL,
    brand_id bigint NOT NULL,
    category_id bigint NOT NULL,
    CONSTRAINT store_product_version_check CHECK ((version >= 0))
);


--
-- Name: store_product_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_product ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_product_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_receiptline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_receiptline (
    id bigint NOT NULL,
    quantity integer NOT NULL,
    sku_snapshot character varying(80) NOT NULL,
    name_snapshot character varying(200) NOT NULL,
    variant_snapshot character varying(150) NOT NULL,
    unit_cost numeric(18,0) NOT NULL,
    receipt_id bigint NOT NULL,
    variant_id bigint NOT NULL,
    CONSTRAINT receipt_cost_nonnegative CHECK (((unit_cost >= (0)::numeric) AND (unit_cost < ('1000000000000000000'::bigint)::numeric))),
    CONSTRAINT receiptline_qty_positive CHECK ((quantity > 0)),
    CONSTRAINT store_receiptline_quantity_check CHECK ((quantity >= 0))
);


--
-- Name: store_receiptline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_receiptline ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_receiptline_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_replenishmentpolicy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_replenishmentpolicy (
    id bigint NOT NULL,
    safety_stock_qty integer NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    product_id bigint NOT NULL,
    updated_by_id bigint NOT NULL,
    CONSTRAINT store_replenishmentpolicy_safety_stock_qty_check CHECK ((safety_stock_qty >= 0))
);


--
-- Name: store_replenishmentpolicy_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_replenishmentpolicy ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_replenishmentpolicy_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_replenishmentsuggestion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_replenishmentsuggestion (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    inventory_qty_snapshot integer NOT NULL,
    inventory_versions jsonb NOT NULL,
    inventory_as_of timestamp with time zone NOT NULL,
    safety_stock_snapshot integer NOT NULL,
    suggested_qty integer NOT NULL,
    status character varying(15) NOT NULL,
    forecast_value_id bigint NOT NULL,
    generated_by_id bigint NOT NULL,
    product_id bigint NOT NULL,
    CONSTRAINT store_replenishmentsuggestion_inventory_qty_snapshot_check CHECK ((inventory_qty_snapshot >= 0)),
    CONSTRAINT store_replenishmentsuggestion_safety_stock_snapshot_check CHECK ((safety_stock_snapshot >= 0)),
    CONSTRAINT store_replenishmentsuggestion_suggested_qty_check CHECK ((suggested_qty >= 0))
);


--
-- Name: store_replenishmentsuggestion_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_replenishmentsuggestion ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_replenishmentsuggestion_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_saleline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_saleline (
    id bigint NOT NULL,
    quantity integer NOT NULL,
    sku_snapshot character varying(80) NOT NULL,
    name_snapshot character varying(200) NOT NULL,
    variant_snapshot character varying(150) NOT NULL,
    unit_price numeric(18,0) NOT NULL,
    sale_id bigint NOT NULL,
    variant_id bigint NOT NULL,
    CONSTRAINT sale_price_positive CHECK (((unit_price > (0)::numeric) AND (unit_price < ('1000000000000000000'::bigint)::numeric))),
    CONSTRAINT saleline_qty_positive CHECK ((quantity > 0)),
    CONSTRAINT store_saleline_quantity_check CHECK ((quantity >= 0))
);


--
-- Name: store_saleline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_saleline ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_saleline_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_saleorder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_saleorder (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(30) NOT NULL,
    status character varying(12) NOT NULL,
    version integer NOT NULL,
    posted_at timestamp with time zone,
    cancel_reason text NOT NULL,
    customer_name_snapshot character varying(200) NOT NULL,
    total_amount numeric(18,0) NOT NULL,
    created_by_id bigint NOT NULL,
    customer_id bigint,
    posted_by_id bigint,
    replacement_for_id bigint,
    stock_posting_id bigint,
    CONSTRAINT sale_total_valid CHECK (((total_amount >= (0)::numeric) AND (total_amount < ('1000000000000000000'::bigint)::numeric))),
    CONSTRAINT saleorder_state_consistent CHECK ((((posted_at IS NOT NULL) AND (posted_by_id IS NOT NULL) AND ((status)::text = 'POSTED'::text) AND (stock_posting_id IS NOT NULL)) OR ((posted_at IS NULL) AND (posted_by_id IS NULL) AND ((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[])) AND (stock_posting_id IS NULL)))),
    CONSTRAINT store_saleorder_version_check CHECK ((version >= 0))
);


--
-- Name: store_saleorder_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_saleorder ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_saleorder_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_salepayment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_salepayment (
    id bigint NOT NULL,
    method character varying(10) NOT NULL,
    amount numeric(18,0) NOT NULL,
    cash_received numeric(18,0),
    change_amount numeric(18,0),
    reference character varying(100) NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    recorded_by_id bigint NOT NULL,
    sale_id bigint NOT NULL,
    CONSTRAINT payment_amount_nonnegative CHECK (((amount >= (0)::numeric) AND (amount < ('1000000000000000000'::bigint)::numeric))),
    CONSTRAINT payment_cash_finite CHECK ((((cash_received IS NULL) OR ((cash_received >= (0)::numeric) AND (cash_received < ('1000000000000000000'::bigint)::numeric))) AND ((change_amount IS NULL) OR ((change_amount >= (0)::numeric) AND (change_amount < ('1000000000000000000'::bigint)::numeric))))),
    CONSTRAINT payment_method_values CHECK ((((cash_received >= amount) AND (cash_received IS NOT NULL) AND (change_amount = (cash_received - amount)) AND (change_amount IS NOT NULL) AND ((method)::text = 'CASH'::text)) OR ((cash_received IS NULL) AND (change_amount IS NULL) AND ((method)::text = ANY ((ARRAY['TRANSFER'::character varying, 'VNPAY'::character varying])::text[])))))
);


--
-- Name: store_salepayment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_salepayment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_salepayment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_shoplocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_shoplocation (
    id smallint NOT NULL,
    address character varying(200) NOT NULL,
    is_example boolean NOT NULL,
    CONSTRAINT shop_example_has_address CHECK (((NOT is_example) OR (NOT ((address)::text = ''::text)))),
    CONSTRAINT shop_location_singleton CHECK ((id = 1)),
    CONSTRAINT store_shoplocation_id_check CHECK ((id >= 0))
);


--
-- Name: store_shoppost; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_shoppost (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    title character varying(160) NOT NULL,
    summary character varying(280) NOT NULL,
    body text NOT NULL,
    published_at timestamp with time zone
);


--
-- Name: store_shoppost_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_shoppost ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_shoppost_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_size; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_size (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(80) NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean NOT NULL,
    version integer NOT NULL,
    CONSTRAINT store_size_version_check CHECK ((version >= 0))
);


--
-- Name: store_size_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_size ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_size_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_sourcefile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_sourcefile (
    id bigint NOT NULL,
    relative_name text NOT NULL,
    sha256 character varying(64) NOT NULL,
    row_count integer NOT NULL,
    schema_version character varying(30) NOT NULL,
    validation_status character varying(15) NOT NULL,
    dataset_version_id bigint NOT NULL,
    CONSTRAINT store_sourcefile_row_count_check CHECK ((row_count >= 0))
);


--
-- Name: store_sourcefile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_sourcefile ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_sourcefile_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_stockadjustment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_stockadjustment (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(30) NOT NULL,
    status character varying(12) NOT NULL,
    version integer NOT NULL,
    posted_at timestamp with time zone,
    cancel_reason text NOT NULL,
    kind character varying(10) NOT NULL,
    reason text NOT NULL,
    source_reference character varying(100) NOT NULL,
    created_by_id bigint NOT NULL,
    posted_by_id bigint,
    stock_posting_id bigint,
    CONSTRAINT stockadjustment_state_consistent CHECK ((((posted_at IS NOT NULL) AND (posted_by_id IS NOT NULL) AND ((status)::text = 'POSTED'::text) AND (stock_posting_id IS NOT NULL)) OR ((posted_at IS NULL) AND (posted_by_id IS NULL) AND ((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[])) AND (stock_posting_id IS NULL)))),
    CONSTRAINT store_stockadjustment_version_check CHECK ((version >= 0))
);


--
-- Name: store_stockadjustment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_stockadjustment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_stockadjustment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_stockbalance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_stockbalance (
    variant_id bigint NOT NULL,
    quantity integer NOT NULL,
    version integer NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT store_stockbalance_quantity_check CHECK ((quantity >= 0)),
    CONSTRAINT store_stockbalance_version_check CHECK ((version >= 0))
);


--
-- Name: store_stockentry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_stockentry (
    id bigint NOT NULL,
    delta integer NOT NULL,
    variant_id bigint NOT NULL,
    posting_id bigint NOT NULL,
    CONSTRAINT entry_nonzero CHECK ((NOT (delta = 0)))
);


--
-- Name: store_stockentry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_stockentry ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_stockentry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_stockposting; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_stockposting (
    id bigint NOT NULL,
    kind character varying(20) NOT NULL,
    business_key character varying(100) NOT NULL,
    posted_at timestamp with time zone NOT NULL,
    posted_by_id bigint NOT NULL
);


--
-- Name: store_stockposting_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_stockposting ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_stockposting_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_supplier; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_supplier (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    code character varying(80) NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean NOT NULL,
    version integer NOT NULL,
    phone character varying(25) NOT NULL,
    address text NOT NULL,
    CONSTRAINT store_supplier_version_check CHECK ((version >= 0))
);


--
-- Name: store_supplier_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_supplier ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_supplier_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_supplierorder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_supplierorder (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    reference character varying(80) NOT NULL,
    ordered_qty integer NOT NULL,
    expected_on date NOT NULL,
    cancelled_at timestamp with time zone,
    created_by_id bigint NOT NULL,
    supplier_id bigint NOT NULL,
    variant_id bigint NOT NULL,
    CONSTRAINT store_supplierorder_ordered_qty_check CHECK ((ordered_qty >= 0)),
    CONSTRAINT supplier_order_positive_qty CHECK ((ordered_qty > 0))
);


--
-- Name: store_supplierorder_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_supplierorder ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_supplierorder_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_systemguard; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_systemguard (
    id smallint NOT NULL,
    version integer NOT NULL,
    data_mode character varying(12) NOT NULL,
    initialized_at timestamp with time zone NOT NULL,
    CONSTRAINT store_systemguard_id_check CHECK ((id >= 0)),
    CONSTRAINT store_systemguard_version_check CHECK ((version >= 0))
);


--
-- Name: store_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_user (
    id bigint NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    username character varying(150) NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL,
    full_name character varying(150) NOT NULL,
    role character varying(12) NOT NULL,
    version integer NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT customer_no_staff_flags CHECK (((NOT ((role)::text = 'CUSTOMER'::text)) OR ((NOT is_staff) AND (NOT is_superuser)))),
    CONSTRAINT store_user_version_check CHECK ((version >= 0)),
    CONSTRAINT user_valid_role CHECK (((role)::text = ANY ((ARRAY['ADMIN'::character varying, 'SALES'::character varying, 'WAREHOUSE'::character varying, 'CUSTOMER'::character varying])::text[])))
);


--
-- Name: store_user_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_user_groups (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    group_id integer NOT NULL
);


--
-- Name: store_user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_user_groups ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_user_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_user ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_user_user_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_user_user_permissions (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: store_user_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_user_user_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_user_user_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_variant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_variant (
    id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    sku character varying(80) NOT NULL,
    selling_price numeric(18,0) NOT NULL,
    low_stock_threshold integer,
    is_active boolean NOT NULL,
    version integer NOT NULL,
    color_id bigint NOT NULL,
    product_id bigint NOT NULL,
    size_id bigint NOT NULL,
    CONSTRAINT store_variant_low_stock_threshold_check CHECK ((low_stock_threshold >= 0)),
    CONSTRAINT store_variant_version_check CHECK ((version >= 0)),
    CONSTRAINT variant_price_nonnegative CHECK (((selling_price >= (0)::numeric) AND (selling_price < ('1000000000000000000'::bigint)::numeric)))
);


--
-- Name: store_variant_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_variant ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_variant_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: store_webguestowner; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_webguestowner (
    owner_hash character varying(64) NOT NULL,
    account_id bigint
);


--
-- Name: store_weborder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_weborder (
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    code character varying(30) NOT NULL,
    request_key uuid NOT NULL,
    owner_hash character varying(64) NOT NULL,
    payload_hash character varying(64) NOT NULL,
    customer_name character varying(150) NOT NULL,
    phone character varying(25) NOT NULL,
    note character varying(1000) NOT NULL,
    status character varying(12) NOT NULL,
    total_amount numeric(18,0) NOT NULL,
    handled_at timestamp with time zone,
    reason character varying(1000) NOT NULL,
    cancel_origin character varying(10) NOT NULL,
    version integer NOT NULL,
    handled_by_id bigint,
    sale_id bigint,
    account_id bigint,
    payment_preference character varying(12) DEFAULT 'UNSPECIFIED'::character varying NOT NULL,
    delivery_address character varying(350) DEFAULT ''::character varying NOT NULL,
    shipment_status character varying(12) DEFAULT ''::character varying NOT NULL,
    tracking_number character varying(100) DEFAULT ''::character varying NOT NULL,
    pickup_expires_at timestamp with time zone,
    pickup_address character varying(200) DEFAULT ''::character varying NOT NULL,
    pickup_address_is_example boolean DEFAULT false NOT NULL,
    CONSTRAINT store_weborder_version_check CHECK ((version >= 0)),
    CONSTRAINT web_order_handling_consistent CHECK (((((status)::text = 'PENDING'::text) AND (handled_by_id IS NULL) AND (handled_at IS NULL) AND ((reason)::text = ''::text) AND ((cancel_origin)::text = ''::text)) OR (((status)::text = 'ACCEPTED'::text) AND (handled_by_id IS NOT NULL) AND (handled_at IS NOT NULL) AND ((reason)::text = ''::text) AND ((cancel_origin)::text = ''::text)) OR (((status)::text = 'CANCELLED'::text) AND (handled_at IS NOT NULL) AND (length(btrim((reason)::text)) > 0) AND ((((cancel_origin)::text = 'STAFF'::text) AND (handled_by_id IS NOT NULL)) OR (((cancel_origin)::text = 'CUSTOMER'::text) AND (handled_by_id IS NULL)))))),
    CONSTRAINT web_order_state_valid CHECK ((((handled_at IS NOT NULL) AND (handled_by_id IS NOT NULL) AND (sale_id IS NOT NULL) AND ((status)::text = 'ACCEPTED'::text)) OR ((sale_id IS NULL) AND ((status)::text = ANY ((ARRAY['PENDING'::character varying, 'CANCELLED'::character varying])::text[]))))),
    CONSTRAINT web_order_total_positive CHECK (((total_amount > (0)::numeric) AND (total_amount < ('1000000000000000000'::bigint)::numeric))),
    CONSTRAINT web_payment_preference_valid CHECK (((payment_preference)::text = ANY ((ARRAY['UNSPECIFIED'::character varying, 'CASH'::character varying, 'TRANSFER'::character varying, 'VNPAY'::character varying])::text[]))),
    CONSTRAINT web_pickup_address_valid CHECK (((((pickup_address)::text = ''::text) AND (NOT pickup_address_is_example)) OR (((delivery_address)::text = ''::text) AND (NOT ((pickup_address)::text = ''::text))))),
    CONSTRAINT web_shipment_fields_valid CHECK (((((delivery_address)::text = ''::text) OR ((payment_preference)::text = 'VNPAY'::text)) AND ((((shipment_status)::text = ''::text) AND ((tracking_number)::text = ''::text)) OR (((shipment_status)::text = ANY ((ARRAY['SHIPPED'::character varying, 'DELIVERED'::character varying])::text[])) AND ((status)::text = 'ACCEPTED'::text) AND (NOT ((delivery_address)::text = ''::text)) AND (NOT ((tracking_number)::text = ''::text))))))
);


--
-- Name: store_weborderline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_weborderline (
    id bigint NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(18,0) NOT NULL,
    name_snapshot character varying(200) NOT NULL,
    sku_snapshot character varying(80) NOT NULL,
    variant_snapshot character varying(150) NOT NULL,
    order_id uuid NOT NULL,
    variant_id bigint NOT NULL,
    CONSTRAINT store_weborderline_quantity_check CHECK ((quantity >= 0)),
    CONSTRAINT web_order_line_price_positive CHECK (((unit_price > (0)::numeric) AND (unit_price < ('1000000000000000000'::bigint)::numeric))),
    CONSTRAINT web_order_quantity_valid CHECK (((quantity > 0) AND (quantity <= 99)))
);


--
-- Name: store_weborderline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.store_weborderline ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.store_weborderline_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: v_nep_don_ban; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_nep_don_ban AS
 WITH lines AS (
         SELECT store_saleline.sale_id,
            count(*) AS so_dong,
            sum(store_saleline.quantity) AS so_luong,
            sum(((store_saleline.quantity)::numeric * store_saleline.unit_price)) AS tong_dong
           FROM public.store_saleline
          GROUP BY store_saleline.sale_id
        )
 SELECT s.id AS don_ban_id,
    s.code AS ma_don,
    s.status AS trang_thai,
    s.created_by_id AS nguoi_lap_id,
    s.posted_at AS ghi_so_luc,
    ((s.posted_at AT TIME ZONE 'Asia/Ho_Chi_Minh'::text))::date AS ngay_ghi_so,
    COALESCE(l.so_dong, (0)::bigint) AS so_dong,
    COALESCE(l.so_luong, (0)::bigint) AS so_luong,
    s.total_amount AS tong_don,
    COALESCE(l.tong_dong, (0)::numeric) AS tong_dong,
    p.method AS phuong_thuc,
    p.amount AS tien_da_ghi_nhan,
    (s.total_amount - COALESCE(l.tong_dong, (0)::numeric)) AS chenh_lech
   FROM ((public.store_saleorder s
     LEFT JOIN lines l ON ((l.sale_id = s.id)))
     LEFT JOIN public.store_salepayment p ON ((p.sale_id = s.id)));


--
-- Name: v_nep_du_bao; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_nep_du_bao AS
 SELECT v.id AS ket_qua_id,
    d.code AS phien_ban_du_lieu,
    d.source_type AS loai_nguon,
    d.status AS trang_thai_du_lieu,
    u.external_key AS ma_nguon,
    u.label AS ten_hien_thi,
    u.granularity AS cap_du_bao,
    u.unit AS don_vi,
    u.scope_key AS pham_vi,
    u.mapping_status AS anh_xa,
    p.code AS ma_san_pham_noi_bo,
    r.cutoff_month AS thang_chot,
    r.target_month AS thang_du_bao,
    m.method AS phuong_phap,
    m.selected_on_validation AS da_chon_bang_kiem_dinh,
    r.status AS trang_thai_chay,
    v.nonnegative_value AS luong_du_bao,
    v.result_status AS trang_thai_ket_qua,
    m.validation_metrics AS sai_so_kiem_dinh,
    m.test_metrics AS sai_so_kiem_tra
   FROM ((((((public.store_forecastvalue v
     JOIN public.store_forecastunit u ON ((u.id = v.forecast_unit_id)))
     LEFT JOIN public.store_product p ON ((p.id = u.internal_product_id)))
     JOIN public.store_forecastrun r ON ((r.id = v.run_id)))
     JOIN public.store_modelresult m ON ((m.id = r.model_result_id)))
     JOIN public.store_experiment x ON ((x.id = m.experiment_id)))
     JOIN public.store_datasetversion d ON ((d.id = x.dataset_version_id)));


--
-- Name: v_nep_so_kho; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_nep_so_kho AS
 SELECT e.id AS dong_so_id,
    v.sku,
    p.code AS ma_san_pham,
    sz.name AS kich_co,
    cl.name AS mau,
    sp.kind AS loai_bien_dong,
    sp.business_key AS khoa_chung_tu,
    e.delta AS thay_doi,
    sp.posted_at AS ghi_so_luc,
    sp.posted_by_id AS nguoi_ghi_so_id
   FROM (((((public.store_stockentry e
     JOIN public.store_stockposting sp ON ((sp.id = e.posting_id)))
     JOIN public.store_variant v ON ((v.id = e.variant_id)))
     JOIN public.store_product p ON ((p.id = v.product_id)))
     JOIN public.store_size sz ON ((sz.id = v.size_id)))
     JOIN public.store_color cl ON ((cl.id = v.color_id)));


--
-- Name: v_nep_su_kien_doanh_thu; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_nep_su_kien_doanh_thu AS
 WITH quantities AS (
         SELECT store_saleline.sale_id,
            sum(store_saleline.quantity) AS quantity
           FROM public.store_saleline
          GROUP BY store_saleline.sale_id
        )
 SELECT 'SALE'::text AS loai,
    s.id AS chung_tu_id,
    s.code AS ma_chung_tu,
    s.code AS ma_goc,
    s.posted_at AS ghi_so_luc,
    ((s.posted_at AT TIME ZONE 'Asia/Ho_Chi_Minh'::text))::date AS ngay_ghi_so,
    s.total_amount AS gia_tri,
    COALESCE(q.quantity, (0)::bigint) AS so_luong
   FROM (public.store_saleorder s
     LEFT JOIN quantities q ON ((q.sale_id = s.id)))
  WHERE ((s.status)::text = 'POSTED'::text)
UNION ALL
 SELECT 'CORRECTION'::text AS loai,
    c.id AS chung_tu_id,
    c.code AS ma_chung_tu,
    s.code AS ma_goc,
    c.posted_at AS ghi_so_luc,
    ((c.posted_at AT TIME ZONE 'Asia/Ho_Chi_Minh'::text))::date AS ngay_ghi_so,
    (- c.amount_snapshot) AS gia_tri,
    (- COALESCE(q.quantity, (0)::bigint)) AS so_luong
   FROM ((public.store_documentcorrection c
     JOIN public.store_saleorder s ON ((s.id = c.original_sale_id)))
     LEFT JOIN quantities q ON ((q.sale_id = s.id)))
  WHERE ((c.status)::text = 'POSTED'::text);


--
-- Name: v_nep_ton_kho; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_nep_ton_kho AS
 WITH ledger AS (
         SELECT store_stockentry.variant_id,
            sum(store_stockentry.delta) AS quantity
           FROM public.store_stockentry
          GROUP BY store_stockentry.variant_id
        )
 SELECT v.id AS bien_the_id,
    p.code AS ma_san_pham,
    p.name AS ten_san_pham,
    v.sku,
    sz.name AS kich_co,
    cl.name AS mau,
    p.unit AS don_vi,
    v.selling_price AS gia_ban,
    b.quantity AS ton_hien_tai,
    COALESCE(l.quantity, (0)::bigint) AS ton_so_kho,
    (b.quantity - COALESCE(l.quantity, (0)::bigint)) AS chenh_lech,
    (v.is_active AND p.is_active AND c.is_active AND br.is_active AND sz.is_active AND cl.is_active AND (v.selling_price > (0)::numeric)) AS dang_ban,
        CASE
            WHEN (v.is_active AND p.is_active AND c.is_active AND br.is_active AND sz.is_active AND cl.is_active AND (v.selling_price > (0)::numeric)) THEN b.quantity
            ELSE 0
        END AS ton_ban_duoc,
    v.low_stock_threshold AS nguong_canh_bao,
    b.version AS phien_ban_ton,
    b.updated_at AS cap_nhat_luc
   FROM (((((((public.store_variant v
     JOIN public.store_product p ON ((p.id = v.product_id)))
     JOIN public.store_category c ON ((c.id = p.category_id)))
     JOIN public.store_brand br ON ((br.id = p.brand_id)))
     JOIN public.store_size sz ON ((sz.id = v.size_id)))
     JOIN public.store_color cl ON ((cl.id = v.color_id)))
     JOIN public.store_stockbalance b ON ((b.variant_id = v.id)))
     LEFT JOIN ledger l ON ((l.variant_id = v.id)));


--
-- Name: v_nep_yeu_cau_web; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_nep_yeu_cau_web AS
 SELECT o.id AS yeu_cau_id,
    o.code AS ma_yeu_cau,
    o.status AS trang_thai_yeu_cau,
    o.sale_id AS don_ban_id,
    s.status AS trang_thai_don_ban,
        CASE
            WHEN ((o.status)::text = 'CANCELLED'::text) THEN 'CANCELLED'::text
            WHEN ((o.status)::text = 'PENDING'::text) THEN 'PENDING'::text
            WHEN ((s.status)::text = 'CANCELLED'::text) THEN 'SALE_CANCELLED'::text
            WHEN (((s.status)::text = 'POSTED'::text) AND (EXISTS ( SELECT 1
               FROM public.store_documentcorrection c
              WHERE ((c.original_sale_id = s.id) AND ((c.status)::text = 'POSTED'::text))))) THEN 'CORRECTED'::text
            WHEN ((s.status)::text = 'POSTED'::text) THEN 'COMPLETED'::text
            ELSE 'ACCEPTED'::text
        END AS trang_thai_thuc_hien,
    o.handled_by_id AS nguoi_xu_ly_id,
    o.handled_at AS xu_ly_luc,
    o.cancel_origin AS ben_huy,
    o.reason AS ly_do
   FROM (public.store_weborder o
     LEFT JOIN public.store_saleorder s ON ((s.id = o.sale_id)));


--
-- Name: store_adjustmentline adjustment_sku_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_adjustmentline
    ADD CONSTRAINT adjustment_sku_unique UNIQUE (adjustment_id, variant_id);


--
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- Name: store_stockentry entry_sku_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockentry
    ADD CONSTRAINT entry_sku_unique UNIQUE (posting_id, variant_id);


--
-- Name: store_modelresult experiment_method_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_modelresult
    ADD CONSTRAINT experiment_method_unique UNIQUE (experiment_id, method);


--
-- Name: store_externalskumap external_map_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_externalskumap
    ADD CONSTRAINT external_map_unique UNIQUE (forecast_unit_id, external_product_id);


--
-- Name: store_forecastunit forecast_unit_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastunit
    ADD CONSTRAINT forecast_unit_unique UNIQUE (dataset_version_id, external_key);


--
-- Name: store_forecastvalue forecast_value_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastvalue
    ADD CONSTRAINT forecast_value_unique UNIQUE (run_id, forecast_unit_id);


--
-- Name: store_monthlysales monthly_unit_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_monthlysales
    ADD CONSTRAINT monthly_unit_unique UNIQUE (forecast_unit_id, month);


--
-- Name: store_operationrequest operation_key_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_operationrequest
    ADD CONSTRAINT operation_key_unique UNIQUE (actor_id, operation, request_key);


--
-- Name: store_receiptline receipt_sku_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_receiptline
    ADD CONSTRAINT receipt_sku_unique UNIQUE (receipt_id, variant_id);


--
-- Name: store_saleline sale_sku_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleline
    ADD CONSTRAINT sale_sku_unique UNIQUE (sale_id, variant_id);


--
-- Name: store_sourcefile source_hash_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_sourcefile
    ADD CONSTRAINT source_hash_unique UNIQUE (dataset_version_id, sha256);


--
-- Name: store_adjustmentline store_adjustmentline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_adjustmentline
    ADD CONSTRAINT store_adjustmentline_pkey PRIMARY KEY (id);


--
-- Name: store_auditevent store_auditevent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_auditevent
    ADD CONSTRAINT store_auditevent_pkey PRIMARY KEY (id);


--
-- Name: store_brand store_brand_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_brand
    ADD CONSTRAINT store_brand_code_key UNIQUE (code);


--
-- Name: store_brand store_brand_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_brand
    ADD CONSTRAINT store_brand_pkey PRIMARY KEY (id);


--
-- Name: store_category store_category_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_category
    ADD CONSTRAINT store_category_code_key UNIQUE (code);


--
-- Name: store_category store_category_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_category
    ADD CONSTRAINT store_category_pkey PRIMARY KEY (id);


--
-- Name: store_color store_color_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_color
    ADD CONSTRAINT store_color_code_key UNIQUE (code);


--
-- Name: store_color store_color_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_color
    ADD CONSTRAINT store_color_pkey PRIMARY KEY (id);


--
-- Name: store_customer store_customer_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_customer
    ADD CONSTRAINT store_customer_code_key UNIQUE (code);


--
-- Name: store_customer store_customer_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_customer
    ADD CONSTRAINT store_customer_pkey PRIMARY KEY (id);


--
-- Name: store_customerloginattempt store_customerloginattempt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_customerloginattempt
    ADD CONSTRAINT store_customerloginattempt_pkey PRIMARY KEY (key);


--
-- Name: store_customerprofile store_customerprofile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_customerprofile
    ADD CONSTRAINT store_customerprofile_pkey PRIMARY KEY (id);


--
-- Name: store_customerprofile store_customerprofile_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_customerprofile
    ADD CONSTRAINT store_customerprofile_user_id_key UNIQUE (user_id);


--
-- Name: store_datasetversion store_datasetversion_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_datasetversion
    ADD CONSTRAINT store_datasetversion_code_key UNIQUE (code);


--
-- Name: store_datasetversion store_datasetversion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_datasetversion
    ADD CONSTRAINT store_datasetversion_pkey PRIMARY KEY (id);


--
-- Name: store_documentcorrection store_documentcorrection_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_documentcorrection
    ADD CONSTRAINT store_documentcorrection_code_key UNIQUE (code);


--
-- Name: store_documentcorrection store_documentcorrection_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_documentcorrection
    ADD CONSTRAINT store_documentcorrection_pkey PRIMARY KEY (id);


--
-- Name: store_documentcorrection store_documentcorrection_stock_posting_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_documentcorrection
    ADD CONSTRAINT store_documentcorrection_stock_posting_id_key UNIQUE (stock_posting_id);


--
-- Name: store_experiment store_experiment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_experiment
    ADD CONSTRAINT store_experiment_pkey PRIMARY KEY (id);


--
-- Name: store_externalskumap store_externalskumap_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_externalskumap
    ADD CONSTRAINT store_externalskumap_pkey PRIMARY KEY (id);


--
-- Name: store_forecastrun store_forecastrun_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastrun
    ADD CONSTRAINT store_forecastrun_pkey PRIMARY KEY (id);


--
-- Name: store_forecastunit store_forecastunit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastunit
    ADD CONSTRAINT store_forecastunit_pkey PRIMARY KEY (id);


--
-- Name: store_forecastvalue store_forecastvalue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastvalue
    ADD CONSTRAINT store_forecastvalue_pkey PRIMARY KEY (id);


--
-- Name: store_gatewaypayment store_gatewaypayment_order_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_gatewaypayment
    ADD CONSTRAINT store_gatewaypayment_order_id_key UNIQUE (order_id);


--
-- Name: store_gatewaypayment store_gatewaypayment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_gatewaypayment
    ADD CONSTRAINT store_gatewaypayment_pkey PRIMARY KEY (id);


--
-- Name: store_gatewaypayment store_gatewaypayment_provider_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_gatewaypayment
    ADD CONSTRAINT store_gatewaypayment_provider_reference_key UNIQUE (provider_reference);


--
-- Name: store_goodsreceipt store_goodsreceipt_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goodsreceipt
    ADD CONSTRAINT store_goodsreceipt_code_key UNIQUE (code);


--
-- Name: store_goodsreceipt store_goodsreceipt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goodsreceipt
    ADD CONSTRAINT store_goodsreceipt_pkey PRIMARY KEY (id);


--
-- Name: store_goodsreceipt store_goodsreceipt_stock_posting_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goodsreceipt
    ADD CONSTRAINT store_goodsreceipt_stock_posting_id_key UNIQUE (stock_posting_id);


--
-- Name: store_modelresult store_modelresult_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_modelresult
    ADD CONSTRAINT store_modelresult_pkey PRIMARY KEY (id);


--
-- Name: store_monthlysales store_monthlysales_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_monthlysales
    ADD CONSTRAINT store_monthlysales_pkey PRIMARY KEY (id);


--
-- Name: store_operationrequest store_operationrequest_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_operationrequest
    ADD CONSTRAINT store_operationrequest_pkey PRIMARY KEY (id);


--
-- Name: store_product store_product_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_product
    ADD CONSTRAINT store_product_code_key UNIQUE (code);


--
-- Name: store_product store_product_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_product
    ADD CONSTRAINT store_product_pkey PRIMARY KEY (id);


--
-- Name: store_receiptline store_receiptline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_receiptline
    ADD CONSTRAINT store_receiptline_pkey PRIMARY KEY (id);


--
-- Name: store_replenishmentpolicy store_replenishmentpolicy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_replenishmentpolicy
    ADD CONSTRAINT store_replenishmentpolicy_pkey PRIMARY KEY (id);


--
-- Name: store_replenishmentsuggestion store_replenishmentsuggestion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_replenishmentsuggestion
    ADD CONSTRAINT store_replenishmentsuggestion_pkey PRIMARY KEY (id);


--
-- Name: store_saleline store_saleline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleline
    ADD CONSTRAINT store_saleline_pkey PRIMARY KEY (id);


--
-- Name: store_saleorder store_saleorder_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleorder
    ADD CONSTRAINT store_saleorder_code_key UNIQUE (code);


--
-- Name: store_saleorder store_saleorder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleorder
    ADD CONSTRAINT store_saleorder_pkey PRIMARY KEY (id);


--
-- Name: store_saleorder store_saleorder_stock_posting_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleorder
    ADD CONSTRAINT store_saleorder_stock_posting_id_key UNIQUE (stock_posting_id);


--
-- Name: store_salepayment store_salepayment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_salepayment
    ADD CONSTRAINT store_salepayment_pkey PRIMARY KEY (id);


--
-- Name: store_salepayment store_salepayment_sale_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_salepayment
    ADD CONSTRAINT store_salepayment_sale_id_key UNIQUE (sale_id);


--
-- Name: store_shoplocation store_shoplocation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_shoplocation
    ADD CONSTRAINT store_shoplocation_pkey PRIMARY KEY (id);


--
-- Name: store_shoppost store_shoppost_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_shoppost
    ADD CONSTRAINT store_shoppost_pkey PRIMARY KEY (id);


--
-- Name: store_size store_size_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_size
    ADD CONSTRAINT store_size_code_key UNIQUE (code);


--
-- Name: store_size store_size_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_size
    ADD CONSTRAINT store_size_pkey PRIMARY KEY (id);


--
-- Name: store_sourcefile store_sourcefile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_sourcefile
    ADD CONSTRAINT store_sourcefile_pkey PRIMARY KEY (id);


--
-- Name: store_stockadjustment store_stockadjustment_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockadjustment
    ADD CONSTRAINT store_stockadjustment_code_key UNIQUE (code);


--
-- Name: store_stockadjustment store_stockadjustment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockadjustment
    ADD CONSTRAINT store_stockadjustment_pkey PRIMARY KEY (id);


--
-- Name: store_stockadjustment store_stockadjustment_stock_posting_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockadjustment
    ADD CONSTRAINT store_stockadjustment_stock_posting_id_key UNIQUE (stock_posting_id);


--
-- Name: store_stockbalance store_stockbalance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockbalance
    ADD CONSTRAINT store_stockbalance_pkey PRIMARY KEY (variant_id);


--
-- Name: store_stockentry store_stockentry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockentry
    ADD CONSTRAINT store_stockentry_pkey PRIMARY KEY (id);


--
-- Name: store_stockposting store_stockposting_business_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockposting
    ADD CONSTRAINT store_stockposting_business_key_key UNIQUE (business_key);


--
-- Name: store_stockposting store_stockposting_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockposting
    ADD CONSTRAINT store_stockposting_pkey PRIMARY KEY (id);


--
-- Name: store_supplier store_supplier_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_supplier
    ADD CONSTRAINT store_supplier_code_key UNIQUE (code);


--
-- Name: store_supplier store_supplier_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_supplier
    ADD CONSTRAINT store_supplier_pkey PRIMARY KEY (id);


--
-- Name: store_supplierorder store_supplierorder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_supplierorder
    ADD CONSTRAINT store_supplierorder_pkey PRIMARY KEY (id);


--
-- Name: store_systemguard store_systemguard_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_systemguard
    ADD CONSTRAINT store_systemguard_pkey PRIMARY KEY (id);


--
-- Name: store_user_groups store_user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user_groups
    ADD CONSTRAINT store_user_groups_pkey PRIMARY KEY (id);


--
-- Name: store_user_groups store_user_groups_user_id_group_id_d5c2dca2_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user_groups
    ADD CONSTRAINT store_user_groups_user_id_group_id_d5c2dca2_uniq UNIQUE (user_id, group_id);


--
-- Name: store_user store_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user
    ADD CONSTRAINT store_user_pkey PRIMARY KEY (id);


--
-- Name: store_user_user_permissions store_user_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user_user_permissions
    ADD CONSTRAINT store_user_user_permissions_pkey PRIMARY KEY (id);


--
-- Name: store_user_user_permissions store_user_user_permissions_user_id_permission_id_bfd44b7c_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user_user_permissions
    ADD CONSTRAINT store_user_user_permissions_user_id_permission_id_bfd44b7c_uniq UNIQUE (user_id, permission_id);


--
-- Name: store_user store_user_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user
    ADD CONSTRAINT store_user_username_key UNIQUE (username);


--
-- Name: store_variant store_variant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_variant
    ADD CONSTRAINT store_variant_pkey PRIMARY KEY (id);


--
-- Name: store_variant store_variant_sku_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_variant
    ADD CONSTRAINT store_variant_sku_key UNIQUE (sku);


--
-- Name: store_webguestowner store_webguestowner_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_webguestowner
    ADD CONSTRAINT store_webguestowner_pkey PRIMARY KEY (owner_hash);


--
-- Name: store_weborder store_weborder_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborder
    ADD CONSTRAINT store_weborder_code_key UNIQUE (code);


--
-- Name: store_weborder store_weborder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborder
    ADD CONSTRAINT store_weborder_pkey PRIMARY KEY (id);


--
-- Name: store_weborder store_weborder_request_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborder
    ADD CONSTRAINT store_weborder_request_key_key UNIQUE (request_key);


--
-- Name: store_weborder store_weborder_sale_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborder
    ADD CONSTRAINT store_weborder_sale_id_key UNIQUE (sale_id);


--
-- Name: store_weborderline store_weborderline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborderline
    ADD CONSTRAINT store_weborderline_pkey PRIMARY KEY (id);


--
-- Name: store_supplierorder supplier_order_unique_line; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_supplierorder
    ADD CONSTRAINT supplier_order_unique_line UNIQUE (supplier_id, reference, variant_id);


--
-- Name: store_variant variant_combination_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_variant
    ADD CONSTRAINT variant_combination_unique UNIQUE (product_id, size_id, color_id);


--
-- Name: store_weborderline web_order_variant_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborderline
    ADD CONSTRAINT web_order_variant_unique UNIQUE (order_id, variant_id);


--
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- Name: nep_supplier_delivery_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX nep_supplier_delivery_reference ON public.store_goodsreceipt USING btree (supplier_order_id, delivery_reference) WHERE (supplier_order_id IS NOT NULL);


--
-- Name: one_current_policy; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_current_policy ON public.store_replenishmentpolicy USING btree (product_id) WHERE (effective_to IS NULL);


--
-- Name: one_posted_receipt_correction; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_posted_receipt_correction ON public.store_documentcorrection USING btree (original_receipt_id) WHERE ((status)::text = 'POSTED'::text);


--
-- Name: one_posted_sale_correction; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_posted_sale_correction ON public.store_documentcorrection USING btree (original_sale_id) WHERE ((status)::text = 'POSTED'::text);


--
-- Name: one_selected_method; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_selected_method ON public.store_modelresult USING btree (experiment_id) WHERE selected_on_validation;


--
-- Name: store_adjustmentline_adjustment_id_b4e7d990; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_adjustmentline_adjustment_id_b4e7d990 ON public.store_adjustmentline USING btree (adjustment_id);


--
-- Name: store_adjustmentline_variant_id_5dc6d51a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_adjustmentline_variant_id_5dc6d51a ON public.store_adjustmentline USING btree (variant_id);


--
-- Name: store_auditevent_actor_id_0a24d0ec; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_auditevent_actor_id_0a24d0ec ON public.store_auditevent USING btree (actor_id);


--
-- Name: store_auditevent_occurred_at_e25a93db; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_auditevent_occurred_at_e25a93db ON public.store_auditevent USING btree (occurred_at);


--
-- Name: store_brand_code_affa05b0_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_brand_code_affa05b0_like ON public.store_brand USING btree (code varchar_pattern_ops);


--
-- Name: store_category_code_68bcc521_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_category_code_68bcc521_like ON public.store_category USING btree (code varchar_pattern_ops);


--
-- Name: store_color_code_2ee6b48c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_color_code_2ee6b48c_like ON public.store_color USING btree (code varchar_pattern_ops);


--
-- Name: store_customer_code_6767bb95_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_customer_code_6767bb95_like ON public.store_customer USING btree (code varchar_pattern_ops);


--
-- Name: store_customerloginattempt_key_d8d671f5_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_customerloginattempt_key_d8d671f5_like ON public.store_customerloginattempt USING btree (key varchar_pattern_ops);


--
-- Name: store_datasetversion_code_ecf2b6e0_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_datasetversion_code_ecf2b6e0_like ON public.store_datasetversion USING btree (code varchar_pattern_ops);


--
-- Name: store_datasetversion_created_by_id_8d6f9fde; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_datasetversion_created_by_id_8d6f9fde ON public.store_datasetversion USING btree (created_by_id);


--
-- Name: store_documentcorrection_code_0ab99504_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_documentcorrection_code_0ab99504_like ON public.store_documentcorrection USING btree (code varchar_pattern_ops);


--
-- Name: store_documentcorrection_created_by_id_2f11a6f1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_documentcorrection_created_by_id_2f11a6f1 ON public.store_documentcorrection USING btree (created_by_id);


--
-- Name: store_documentcorrection_original_receipt_id_af6d9fd3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_documentcorrection_original_receipt_id_af6d9fd3 ON public.store_documentcorrection USING btree (original_receipt_id);


--
-- Name: store_documentcorrection_original_sale_id_f559424f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_documentcorrection_original_sale_id_f559424f ON public.store_documentcorrection USING btree (original_sale_id);


--
-- Name: store_documentcorrection_posted_at_9583149a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_documentcorrection_posted_at_9583149a ON public.store_documentcorrection USING btree (posted_at);


--
-- Name: store_documentcorrection_posted_by_id_f47a5262; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_documentcorrection_posted_by_id_f47a5262 ON public.store_documentcorrection USING btree (posted_by_id);


--
-- Name: store_documentcorrection_status_ff096140; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_documentcorrection_status_ff096140 ON public.store_documentcorrection USING btree (status);


--
-- Name: store_documentcorrection_status_ff096140_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_documentcorrection_status_ff096140_like ON public.store_documentcorrection USING btree (status varchar_pattern_ops);


--
-- Name: store_experiment_dataset_version_id_2d6af2f7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_experiment_dataset_version_id_2d6af2f7 ON public.store_experiment USING btree (dataset_version_id);


--
-- Name: store_externalskumap_forecast_unit_id_62d72d73; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_externalskumap_forecast_unit_id_62d72d73 ON public.store_externalskumap USING btree (forecast_unit_id);


--
-- Name: store_externalskumap_internal_variant_id_3cab8280; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_externalskumap_internal_variant_id_3cab8280 ON public.store_externalskumap USING btree (internal_variant_id);


--
-- Name: store_externalskumap_verified_by_id_ed3f21b0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_externalskumap_verified_by_id_ed3f21b0 ON public.store_externalskumap USING btree (verified_by_id);


--
-- Name: store_forecastrun_model_result_id_e47d75e4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_forecastrun_model_result_id_e47d75e4 ON public.store_forecastrun USING btree (model_result_id);


--
-- Name: store_forecastunit_dataset_version_id_b06ee565; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_forecastunit_dataset_version_id_b06ee565 ON public.store_forecastunit USING btree (dataset_version_id);


--
-- Name: store_forecastunit_internal_product_id_0366b7f6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_forecastunit_internal_product_id_0366b7f6 ON public.store_forecastunit USING btree (internal_product_id);


--
-- Name: store_forecastvalue_forecast_unit_id_2b236267; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_forecastvalue_forecast_unit_id_2b236267 ON public.store_forecastvalue USING btree (forecast_unit_id);


--
-- Name: store_forecastvalue_run_id_3b0f48d8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_forecastvalue_run_id_3b0f48d8 ON public.store_forecastvalue USING btree (run_id);


--
-- Name: store_gatewaypayment_provider_reference_dc9e79c2_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_gatewaypayment_provider_reference_dc9e79c2_like ON public.store_gatewaypayment USING btree (provider_reference varchar_pattern_ops);


--
-- Name: store_goodsreceipt_code_42fb2ff6_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_goodsreceipt_code_42fb2ff6_like ON public.store_goodsreceipt USING btree (code varchar_pattern_ops);


--
-- Name: store_goodsreceipt_created_by_id_6e6a1136; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_goodsreceipt_created_by_id_6e6a1136 ON public.store_goodsreceipt USING btree (created_by_id);


--
-- Name: store_goodsreceipt_posted_at_7ccefa98; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_goodsreceipt_posted_at_7ccefa98 ON public.store_goodsreceipt USING btree (posted_at);


--
-- Name: store_goodsreceipt_posted_by_id_a30ccad3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_goodsreceipt_posted_by_id_a30ccad3 ON public.store_goodsreceipt USING btree (posted_by_id);


--
-- Name: store_goodsreceipt_status_d1ce2c74; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_goodsreceipt_status_d1ce2c74 ON public.store_goodsreceipt USING btree (status);


--
-- Name: store_goodsreceipt_status_d1ce2c74_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_goodsreceipt_status_d1ce2c74_like ON public.store_goodsreceipt USING btree (status varchar_pattern_ops);


--
-- Name: store_goodsreceipt_supplier_id_46355758; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_goodsreceipt_supplier_id_46355758 ON public.store_goodsreceipt USING btree (supplier_id);


--
-- Name: store_goodsreceipt_supplier_order_id_aa9fe890; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_goodsreceipt_supplier_order_id_aa9fe890 ON public.store_goodsreceipt USING btree (supplier_order_id);


--
-- Name: store_modelresult_experiment_id_718c9aee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_modelresult_experiment_id_718c9aee ON public.store_modelresult USING btree (experiment_id);


--
-- Name: store_monthlysales_forecast_unit_id_76038f58; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_monthlysales_forecast_unit_id_76038f58 ON public.store_monthlysales USING btree (forecast_unit_id);


--
-- Name: store_operationrequest_actor_id_dcd5841a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_operationrequest_actor_id_dcd5841a ON public.store_operationrequest USING btree (actor_id);


--
-- Name: store_product_brand_id_ec9e66ab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_product_brand_id_ec9e66ab ON public.store_product USING btree (brand_id);


--
-- Name: store_product_category_id_574bae65; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_product_category_id_574bae65 ON public.store_product USING btree (category_id);


--
-- Name: store_product_code_1c3364d5_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_product_code_1c3364d5_like ON public.store_product USING btree (code varchar_pattern_ops);


--
-- Name: store_receiptline_receipt_id_84259751; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_receiptline_receipt_id_84259751 ON public.store_receiptline USING btree (receipt_id);


--
-- Name: store_receiptline_variant_id_c6dfa667; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_receiptline_variant_id_c6dfa667 ON public.store_receiptline USING btree (variant_id);


--
-- Name: store_replenishmentpolicy_product_id_d755a517; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_replenishmentpolicy_product_id_d755a517 ON public.store_replenishmentpolicy USING btree (product_id);


--
-- Name: store_replenishmentpolicy_updated_by_id_a0a41f50; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_replenishmentpolicy_updated_by_id_a0a41f50 ON public.store_replenishmentpolicy USING btree (updated_by_id);


--
-- Name: store_replenishmentsuggestion_forecast_value_id_373db9cc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_replenishmentsuggestion_forecast_value_id_373db9cc ON public.store_replenishmentsuggestion USING btree (forecast_value_id);


--
-- Name: store_replenishmentsuggestion_generated_by_id_56f463c6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_replenishmentsuggestion_generated_by_id_56f463c6 ON public.store_replenishmentsuggestion USING btree (generated_by_id);


--
-- Name: store_replenishmentsuggestion_product_id_c359b4ec; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_replenishmentsuggestion_product_id_c359b4ec ON public.store_replenishmentsuggestion USING btree (product_id);


--
-- Name: store_saleline_sale_id_5e25b3a4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleline_sale_id_5e25b3a4 ON public.store_saleline USING btree (sale_id);


--
-- Name: store_saleline_variant_id_f2c928f3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleline_variant_id_f2c928f3 ON public.store_saleline USING btree (variant_id);


--
-- Name: store_saleorder_code_8d4a7cb8_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleorder_code_8d4a7cb8_like ON public.store_saleorder USING btree (code varchar_pattern_ops);


--
-- Name: store_saleorder_created_by_id_0cbcc9a1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleorder_created_by_id_0cbcc9a1 ON public.store_saleorder USING btree (created_by_id);


--
-- Name: store_saleorder_customer_id_8e4c266a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleorder_customer_id_8e4c266a ON public.store_saleorder USING btree (customer_id);


--
-- Name: store_saleorder_posted_at_eba6dd61; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleorder_posted_at_eba6dd61 ON public.store_saleorder USING btree (posted_at);


--
-- Name: store_saleorder_posted_by_id_1c5bcaca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleorder_posted_by_id_1c5bcaca ON public.store_saleorder USING btree (posted_by_id);


--
-- Name: store_saleorder_replacement_for_id_197e287a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleorder_replacement_for_id_197e287a ON public.store_saleorder USING btree (replacement_for_id);


--
-- Name: store_saleorder_status_efe3a63b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleorder_status_efe3a63b ON public.store_saleorder USING btree (status);


--
-- Name: store_saleorder_status_efe3a63b_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_saleorder_status_efe3a63b_like ON public.store_saleorder USING btree (status varchar_pattern_ops);


--
-- Name: store_salepayment_recorded_by_id_8f6e38bb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_salepayment_recorded_by_id_8f6e38bb ON public.store_salepayment USING btree (recorded_by_id);


--
-- Name: store_shoppost_published_at_968230cf; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_shoppost_published_at_968230cf ON public.store_shoppost USING btree (published_at);


--
-- Name: store_size_code_fc9128e4_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_size_code_fc9128e4_like ON public.store_size USING btree (code varchar_pattern_ops);


--
-- Name: store_sourcefile_dataset_version_id_70f391d5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_sourcefile_dataset_version_id_70f391d5 ON public.store_sourcefile USING btree (dataset_version_id);


--
-- Name: store_stockadjustment_code_db6167d8_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockadjustment_code_db6167d8_like ON public.store_stockadjustment USING btree (code varchar_pattern_ops);


--
-- Name: store_stockadjustment_created_by_id_73f56a63; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockadjustment_created_by_id_73f56a63 ON public.store_stockadjustment USING btree (created_by_id);


--
-- Name: store_stockadjustment_posted_at_e417ec58; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockadjustment_posted_at_e417ec58 ON public.store_stockadjustment USING btree (posted_at);


--
-- Name: store_stockadjustment_posted_by_id_11d01ddf; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockadjustment_posted_by_id_11d01ddf ON public.store_stockadjustment USING btree (posted_by_id);


--
-- Name: store_stockadjustment_status_f26d8020; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockadjustment_status_f26d8020 ON public.store_stockadjustment USING btree (status);


--
-- Name: store_stockadjustment_status_f26d8020_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockadjustment_status_f26d8020_like ON public.store_stockadjustment USING btree (status varchar_pattern_ops);


--
-- Name: store_stockentry_posting_id_ea02c582; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockentry_posting_id_ea02c582 ON public.store_stockentry USING btree (posting_id);


--
-- Name: store_stockentry_variant_id_e9265a32; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockentry_variant_id_e9265a32 ON public.store_stockentry USING btree (variant_id);


--
-- Name: store_stockposting_business_key_428f277a_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockposting_business_key_428f277a_like ON public.store_stockposting USING btree (business_key varchar_pattern_ops);


--
-- Name: store_stockposting_posted_at_abaf4f1b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockposting_posted_at_abaf4f1b ON public.store_stockposting USING btree (posted_at);


--
-- Name: store_stockposting_posted_by_id_8e9c7785; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_stockposting_posted_by_id_8e9c7785 ON public.store_stockposting USING btree (posted_by_id);


--
-- Name: store_supplier_code_8d7a5e5c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_supplier_code_8d7a5e5c_like ON public.store_supplier USING btree (code varchar_pattern_ops);


--
-- Name: store_supplierorder_created_by_id_a478ae7a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_supplierorder_created_by_id_a478ae7a ON public.store_supplierorder USING btree (created_by_id);


--
-- Name: store_supplierorder_supplier_id_edfeb562; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_supplierorder_supplier_id_edfeb562 ON public.store_supplierorder USING btree (supplier_id);


--
-- Name: store_supplierorder_variant_id_52070984; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_supplierorder_variant_id_52070984 ON public.store_supplierorder USING btree (variant_id);


--
-- Name: store_user_groups_group_id_def3ecb1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_user_groups_group_id_def3ecb1 ON public.store_user_groups USING btree (group_id);


--
-- Name: store_user_groups_user_id_f76ad019; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_user_groups_user_id_f76ad019 ON public.store_user_groups USING btree (user_id);


--
-- Name: store_user_user_permissions_permission_id_d9830978; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_user_user_permissions_permission_id_d9830978 ON public.store_user_user_permissions USING btree (permission_id);


--
-- Name: store_user_user_permissions_user_id_31a90150; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_user_user_permissions_user_id_31a90150 ON public.store_user_user_permissions USING btree (user_id);


--
-- Name: store_user_username_c2c55c55_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_user_username_c2c55c55_like ON public.store_user USING btree (username varchar_pattern_ops);


--
-- Name: store_variant_color_id_e9bee998; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_variant_color_id_e9bee998 ON public.store_variant USING btree (color_id);


--
-- Name: store_variant_product_id_3c4bd418; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_variant_product_id_3c4bd418 ON public.store_variant USING btree (product_id);


--
-- Name: store_variant_size_id_7b4978ce; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_variant_size_id_7b4978ce ON public.store_variant USING btree (size_id);


--
-- Name: store_variant_sku_5c0b5f21_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_variant_sku_5c0b5f21_like ON public.store_variant USING btree (sku varchar_pattern_ops);


--
-- Name: store_webguestowner_account_id_97f7a692; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_webguestowner_account_id_97f7a692 ON public.store_webguestowner USING btree (account_id);


--
-- Name: store_webguestowner_owner_hash_06c6bef6_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_webguestowner_owner_hash_06c6bef6_like ON public.store_webguestowner USING btree (owner_hash varchar_pattern_ops);


--
-- Name: store_weborder_account_id_ebf2c6c8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborder_account_id_ebf2c6c8 ON public.store_weborder USING btree (account_id);


--
-- Name: store_weborder_code_062417db_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborder_code_062417db_like ON public.store_weborder USING btree (code varchar_pattern_ops);


--
-- Name: store_weborder_handled_by_id_57f70f35; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborder_handled_by_id_57f70f35 ON public.store_weborder USING btree (handled_by_id);


--
-- Name: store_weborder_owner_hash_9b754e76; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborder_owner_hash_9b754e76 ON public.store_weborder USING btree (owner_hash);


--
-- Name: store_weborder_owner_hash_9b754e76_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborder_owner_hash_9b754e76_like ON public.store_weborder USING btree (owner_hash varchar_pattern_ops);


--
-- Name: store_weborder_status_f5a1eed3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborder_status_f5a1eed3 ON public.store_weborder USING btree (status);


--
-- Name: store_weborder_status_f5a1eed3_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborder_status_f5a1eed3_like ON public.store_weborder USING btree (status varchar_pattern_ops);


--
-- Name: store_weborderline_order_id_754877de; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborderline_order_id_754877de ON public.store_weborderline USING btree (order_id);


--
-- Name: store_weborderline_variant_id_a7b8e160; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX store_weborderline_variant_id_a7b8e160 ON public.store_weborderline USING btree (variant_id);


--
-- Name: user_username_ci; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX user_username_ci ON public.store_user USING btree (lower((username)::text));


--
-- Name: store_stockbalance nep_balance_check; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_balance_check AFTER INSERT OR DELETE OR UPDATE ON public.store_stockbalance DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_balance_check();


--
-- Name: store_stockentry nep_balance_check; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_balance_check AFTER INSERT OR DELETE OR UPDATE ON public.store_stockentry DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_balance_check();


--
-- Name: store_adjustmentline nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_adjustmentline DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_documentcorrection nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_documentcorrection DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_goodsreceipt nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_goodsreceipt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_receiptline nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_receiptline DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_saleline nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_saleline DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_saleorder nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_saleorder DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_salepayment nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_salepayment DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_stockadjustment nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_stockadjustment DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_stockentry nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_stockentry DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_stockposting nep_check_commit; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_check_commit AFTER INSERT OR DELETE OR UPDATE ON public.store_stockposting DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_check_commit();


--
-- Name: store_documentcorrection nep_doc_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_doc_guard BEFORE INSERT OR DELETE OR UPDATE ON public.store_documentcorrection FOR EACH ROW EXECUTE FUNCTION public.nep_doc_guard();


--
-- Name: store_goodsreceipt nep_doc_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_doc_guard BEFORE INSERT OR DELETE OR UPDATE ON public.store_goodsreceipt FOR EACH ROW EXECUTE FUNCTION public.nep_doc_guard();


--
-- Name: store_saleorder nep_doc_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_doc_guard BEFORE INSERT OR DELETE OR UPDATE ON public.store_saleorder FOR EACH ROW EXECUTE FUNCTION public.nep_doc_guard();


--
-- Name: store_stockadjustment nep_doc_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_doc_guard BEFORE INSERT OR DELETE OR UPDATE ON public.store_stockadjustment FOR EACH ROW EXECUTE FUNCTION public.nep_doc_guard();


--
-- Name: store_experiment nep_forecast_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_forecast_guard AFTER INSERT OR UPDATE ON public.store_experiment DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_forecast_guard();


--
-- Name: store_forecastrun nep_forecast_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_forecast_guard AFTER INSERT OR UPDATE ON public.store_forecastrun DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_forecast_guard();


--
-- Name: store_forecastunit nep_forecast_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_forecast_guard AFTER INSERT OR UPDATE ON public.store_forecastunit DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_forecast_guard();


--
-- Name: store_forecastvalue nep_forecast_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_forecast_guard AFTER INSERT OR UPDATE ON public.store_forecastvalue DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_forecast_guard();


--
-- Name: store_modelresult nep_forecast_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_forecast_guard AFTER INSERT OR UPDATE ON public.store_modelresult DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_forecast_guard();


--
-- Name: store_salepayment nep_gateway_sale_matches; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_gateway_sale_matches BEFORE INSERT ON public.store_salepayment FOR EACH ROW EXECUTE FUNCTION public.nep_check_gateway_sale();


--
-- Name: store_auditevent nep_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_immutable BEFORE DELETE OR UPDATE ON public.store_auditevent FOR EACH ROW EXECUTE FUNCTION public.nep_immutable();


--
-- Name: store_salepayment nep_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_immutable BEFORE DELETE OR UPDATE ON public.store_salepayment FOR EACH ROW EXECUTE FUNCTION public.nep_immutable();


--
-- Name: store_stockentry nep_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_immutable BEFORE DELETE OR UPDATE ON public.store_stockentry FOR EACH ROW EXECUTE FUNCTION public.nep_immutable();


--
-- Name: store_stockposting nep_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_immutable BEFORE DELETE OR UPDATE ON public.store_stockposting FOR EACH ROW EXECUTE FUNCTION public.nep_immutable();


--
-- Name: store_adjustmentline nep_line_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_line_guard BEFORE INSERT OR DELETE OR UPDATE ON public.store_adjustmentline FOR EACH ROW EXECUTE FUNCTION public.nep_line_guard();


--
-- Name: store_receiptline nep_line_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_line_guard BEFORE INSERT OR DELETE OR UPDATE ON public.store_receiptline FOR EACH ROW EXECUTE FUNCTION public.nep_line_guard();


--
-- Name: store_saleline nep_line_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_line_guard BEFORE INSERT OR DELETE OR UPDATE ON public.store_saleline FOR EACH ROW EXECUTE FUNCTION public.nep_line_guard();


--
-- Name: store_adjustmentline nep_parent_link_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_parent_link_guard BEFORE UPDATE ON public.store_adjustmentline FOR EACH ROW EXECUTE FUNCTION public.nep_parent_link_guard();


--
-- Name: store_receiptline nep_parent_link_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_parent_link_guard BEFORE UPDATE ON public.store_receiptline FOR EACH ROW EXECUTE FUNCTION public.nep_parent_link_guard();


--
-- Name: store_saleline nep_parent_link_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_parent_link_guard BEFORE UPDATE ON public.store_saleline FOR EACH ROW EXECUTE FUNCTION public.nep_parent_link_guard();


--
-- Name: store_stockbalance nep_parent_link_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_parent_link_guard BEFORE UPDATE ON public.store_stockbalance FOR EACH ROW EXECUTE FUNCTION public.nep_parent_link_guard();


--
-- Name: store_product nep_product_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_product_guard BEFORE UPDATE ON public.store_product FOR EACH ROW EXECUTE FUNCTION public.nep_product_guard();


--
-- Name: store_weborder nep_shipment_transition; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_shipment_transition BEFORE UPDATE ON public.store_weborder FOR EACH ROW EXECUTE FUNCTION public.nep_check_shipment();


--
-- Name: store_goodsreceipt nep_supplier_receipt_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_supplier_receipt_guard BEFORE INSERT OR UPDATE ON public.store_goodsreceipt FOR EACH ROW EXECUTE FUNCTION public.nep_check_supplier_receipt();


--
-- Name: store_variant nep_variant_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_variant_guard BEFORE UPDATE ON public.store_variant FOR EACH ROW EXECUTE FUNCTION public.nep_variant_guard();


--
-- Name: store_variant nep_variant_has_balance; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_variant_has_balance AFTER INSERT ON public.store_variant DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_balance_check();


--
-- Name: store_weborder nep_web_check; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_web_check AFTER INSERT OR UPDATE ON public.store_weborder DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_web_check();


--
-- Name: store_weborderline nep_web_check; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER nep_web_check AFTER INSERT OR DELETE OR UPDATE ON public.store_weborderline DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_web_check();


--
-- Name: store_weborderline nep_web_line_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_web_line_immutable BEFORE DELETE OR UPDATE ON public.store_weborderline FOR EACH ROW EXECUTE FUNCTION public.nep_immutable();


--
-- Name: store_weborder nep_web_snapshot_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_web_snapshot_guard BEFORE DELETE OR UPDATE ON public.store_weborder FOR EACH ROW EXECUTE FUNCTION public.nep_web_snapshot_guard();


--
-- Name: store_weborder nep_web_transition_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER nep_web_transition_guard BEFORE INSERT OR UPDATE ON public.store_weborder FOR EACH ROW EXECUTE FUNCTION public.nep_web_transition_guard();


--
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_adjustmentline store_adjustmentline_adjustment_id_b4e7d990_fk_store_sto; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_adjustmentline
    ADD CONSTRAINT store_adjustmentline_adjustment_id_b4e7d990_fk_store_sto FOREIGN KEY (adjustment_id) REFERENCES public.store_stockadjustment(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_adjustmentline store_adjustmentline_variant_id_5dc6d51a_fk_store_variant_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_adjustmentline
    ADD CONSTRAINT store_adjustmentline_variant_id_5dc6d51a_fk_store_variant_id FOREIGN KEY (variant_id) REFERENCES public.store_variant(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_auditevent store_auditevent_actor_id_0a24d0ec_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_auditevent
    ADD CONSTRAINT store_auditevent_actor_id_0a24d0ec_fk_store_user_id FOREIGN KEY (actor_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_customerprofile store_customerprofile_user_id_114129a5_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_customerprofile
    ADD CONSTRAINT store_customerprofile_user_id_114129a5_fk_store_user_id FOREIGN KEY (user_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_datasetversion store_datasetversion_created_by_id_8d6f9fde_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_datasetversion
    ADD CONSTRAINT store_datasetversion_created_by_id_8d6f9fde_fk_store_user_id FOREIGN KEY (created_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_documentcorrection store_documentcorrec_created_by_id_2f11a6f1_fk_store_use; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_documentcorrection
    ADD CONSTRAINT store_documentcorrec_created_by_id_2f11a6f1_fk_store_use FOREIGN KEY (created_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_documentcorrection store_documentcorrec_original_receipt_id_af6d9fd3_fk_store_goo; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_documentcorrection
    ADD CONSTRAINT store_documentcorrec_original_receipt_id_af6d9fd3_fk_store_goo FOREIGN KEY (original_receipt_id) REFERENCES public.store_goodsreceipt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_documentcorrection store_documentcorrec_original_sale_id_f559424f_fk_store_sal; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_documentcorrection
    ADD CONSTRAINT store_documentcorrec_original_sale_id_f559424f_fk_store_sal FOREIGN KEY (original_sale_id) REFERENCES public.store_saleorder(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_documentcorrection store_documentcorrec_stock_posting_id_a5f1c743_fk_store_sto; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_documentcorrection
    ADD CONSTRAINT store_documentcorrec_stock_posting_id_a5f1c743_fk_store_sto FOREIGN KEY (stock_posting_id) REFERENCES public.store_stockposting(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_documentcorrection store_documentcorrection_posted_by_id_f47a5262_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_documentcorrection
    ADD CONSTRAINT store_documentcorrection_posted_by_id_f47a5262_fk_store_user_id FOREIGN KEY (posted_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_experiment store_experiment_dataset_version_id_2d6af2f7_fk_store_dat; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_experiment
    ADD CONSTRAINT store_experiment_dataset_version_id_2d6af2f7_fk_store_dat FOREIGN KEY (dataset_version_id) REFERENCES public.store_datasetversion(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_externalskumap store_externalskumap_forecast_unit_id_62d72d73_fk_store_for; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_externalskumap
    ADD CONSTRAINT store_externalskumap_forecast_unit_id_62d72d73_fk_store_for FOREIGN KEY (forecast_unit_id) REFERENCES public.store_forecastunit(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_externalskumap store_externalskumap_internal_variant_id_3cab8280_fk_store_var; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_externalskumap
    ADD CONSTRAINT store_externalskumap_internal_variant_id_3cab8280_fk_store_var FOREIGN KEY (internal_variant_id) REFERENCES public.store_variant(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_externalskumap store_externalskumap_verified_by_id_ed3f21b0_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_externalskumap
    ADD CONSTRAINT store_externalskumap_verified_by_id_ed3f21b0_fk_store_user_id FOREIGN KEY (verified_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_forecastrun store_forecastrun_model_result_id_e47d75e4_fk_store_mod; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastrun
    ADD CONSTRAINT store_forecastrun_model_result_id_e47d75e4_fk_store_mod FOREIGN KEY (model_result_id) REFERENCES public.store_modelresult(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_forecastunit store_forecastunit_dataset_version_id_b06ee565_fk_store_dat; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastunit
    ADD CONSTRAINT store_forecastunit_dataset_version_id_b06ee565_fk_store_dat FOREIGN KEY (dataset_version_id) REFERENCES public.store_datasetversion(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_forecastunit store_forecastunit_internal_product_id_0366b7f6_fk_store_pro; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastunit
    ADD CONSTRAINT store_forecastunit_internal_product_id_0366b7f6_fk_store_pro FOREIGN KEY (internal_product_id) REFERENCES public.store_product(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_forecastvalue store_forecastvalue_forecast_unit_id_2b236267_fk_store_for; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastvalue
    ADD CONSTRAINT store_forecastvalue_forecast_unit_id_2b236267_fk_store_for FOREIGN KEY (forecast_unit_id) REFERENCES public.store_forecastunit(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_forecastvalue store_forecastvalue_run_id_3b0f48d8_fk_store_forecastrun_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_forecastvalue
    ADD CONSTRAINT store_forecastvalue_run_id_3b0f48d8_fk_store_forecastrun_id FOREIGN KEY (run_id) REFERENCES public.store_forecastrun(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_gatewaypayment store_gatewaypayment_order_id_da67306b_fk_store_weborder_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_gatewaypayment
    ADD CONSTRAINT store_gatewaypayment_order_id_da67306b_fk_store_weborder_id FOREIGN KEY (order_id) REFERENCES public.store_weborder(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_goodsreceipt store_goodsreceipt_created_by_id_6e6a1136_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goodsreceipt
    ADD CONSTRAINT store_goodsreceipt_created_by_id_6e6a1136_fk_store_user_id FOREIGN KEY (created_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_goodsreceipt store_goodsreceipt_posted_by_id_a30ccad3_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goodsreceipt
    ADD CONSTRAINT store_goodsreceipt_posted_by_id_a30ccad3_fk_store_user_id FOREIGN KEY (posted_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_goodsreceipt store_goodsreceipt_stock_posting_id_18769dc4_fk_store_sto; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goodsreceipt
    ADD CONSTRAINT store_goodsreceipt_stock_posting_id_18769dc4_fk_store_sto FOREIGN KEY (stock_posting_id) REFERENCES public.store_stockposting(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_goodsreceipt store_goodsreceipt_supplier_id_46355758_fk_store_supplier_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goodsreceipt
    ADD CONSTRAINT store_goodsreceipt_supplier_id_46355758_fk_store_supplier_id FOREIGN KEY (supplier_id) REFERENCES public.store_supplier(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_goodsreceipt store_goodsreceipt_supplier_order_id_aa9fe890_fk_store_sup; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goodsreceipt
    ADD CONSTRAINT store_goodsreceipt_supplier_order_id_aa9fe890_fk_store_sup FOREIGN KEY (supplier_order_id) REFERENCES public.store_supplierorder(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_modelresult store_modelresult_experiment_id_718c9aee_fk_store_experiment_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_modelresult
    ADD CONSTRAINT store_modelresult_experiment_id_718c9aee_fk_store_experiment_id FOREIGN KEY (experiment_id) REFERENCES public.store_experiment(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_monthlysales store_monthlysales_forecast_unit_id_76038f58_fk_store_for; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_monthlysales
    ADD CONSTRAINT store_monthlysales_forecast_unit_id_76038f58_fk_store_for FOREIGN KEY (forecast_unit_id) REFERENCES public.store_forecastunit(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_operationrequest store_operationrequest_actor_id_dcd5841a_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_operationrequest
    ADD CONSTRAINT store_operationrequest_actor_id_dcd5841a_fk_store_user_id FOREIGN KEY (actor_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_product store_product_brand_id_ec9e66ab_fk_store_brand_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_product
    ADD CONSTRAINT store_product_brand_id_ec9e66ab_fk_store_brand_id FOREIGN KEY (brand_id) REFERENCES public.store_brand(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_product store_product_category_id_574bae65_fk_store_category_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_product
    ADD CONSTRAINT store_product_category_id_574bae65_fk_store_category_id FOREIGN KEY (category_id) REFERENCES public.store_category(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_receiptline store_receiptline_receipt_id_84259751_fk_store_goodsreceipt_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_receiptline
    ADD CONSTRAINT store_receiptline_receipt_id_84259751_fk_store_goodsreceipt_id FOREIGN KEY (receipt_id) REFERENCES public.store_goodsreceipt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_receiptline store_receiptline_variant_id_c6dfa667_fk_store_variant_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_receiptline
    ADD CONSTRAINT store_receiptline_variant_id_c6dfa667_fk_store_variant_id FOREIGN KEY (variant_id) REFERENCES public.store_variant(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_replenishmentpolicy store_replenishmentp_product_id_d755a517_fk_store_pro; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_replenishmentpolicy
    ADD CONSTRAINT store_replenishmentp_product_id_d755a517_fk_store_pro FOREIGN KEY (product_id) REFERENCES public.store_product(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_replenishmentpolicy store_replenishmentp_updated_by_id_a0a41f50_fk_store_use; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_replenishmentpolicy
    ADD CONSTRAINT store_replenishmentp_updated_by_id_a0a41f50_fk_store_use FOREIGN KEY (updated_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_replenishmentsuggestion store_replenishments_forecast_value_id_373db9cc_fk_store_for; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_replenishmentsuggestion
    ADD CONSTRAINT store_replenishments_forecast_value_id_373db9cc_fk_store_for FOREIGN KEY (forecast_value_id) REFERENCES public.store_forecastvalue(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_replenishmentsuggestion store_replenishments_generated_by_id_56f463c6_fk_store_use; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_replenishmentsuggestion
    ADD CONSTRAINT store_replenishments_generated_by_id_56f463c6_fk_store_use FOREIGN KEY (generated_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_replenishmentsuggestion store_replenishments_product_id_c359b4ec_fk_store_pro; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_replenishmentsuggestion
    ADD CONSTRAINT store_replenishments_product_id_c359b4ec_fk_store_pro FOREIGN KEY (product_id) REFERENCES public.store_product(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_saleline store_saleline_sale_id_5e25b3a4_fk_store_saleorder_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleline
    ADD CONSTRAINT store_saleline_sale_id_5e25b3a4_fk_store_saleorder_id FOREIGN KEY (sale_id) REFERENCES public.store_saleorder(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_saleline store_saleline_variant_id_f2c928f3_fk_store_variant_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleline
    ADD CONSTRAINT store_saleline_variant_id_f2c928f3_fk_store_variant_id FOREIGN KEY (variant_id) REFERENCES public.store_variant(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_saleorder store_saleorder_created_by_id_0cbcc9a1_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleorder
    ADD CONSTRAINT store_saleorder_created_by_id_0cbcc9a1_fk_store_user_id FOREIGN KEY (created_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_saleorder store_saleorder_customer_id_8e4c266a_fk_store_customer_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleorder
    ADD CONSTRAINT store_saleorder_customer_id_8e4c266a_fk_store_customer_id FOREIGN KEY (customer_id) REFERENCES public.store_customer(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_saleorder store_saleorder_posted_by_id_1c5bcaca_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleorder
    ADD CONSTRAINT store_saleorder_posted_by_id_1c5bcaca_fk_store_user_id FOREIGN KEY (posted_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_saleorder store_saleorder_replacement_for_id_197e287a_fk_store_sal; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleorder
    ADD CONSTRAINT store_saleorder_replacement_for_id_197e287a_fk_store_sal FOREIGN KEY (replacement_for_id) REFERENCES public.store_saleorder(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_saleorder store_saleorder_stock_posting_id_939235cb_fk_store_sto; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_saleorder
    ADD CONSTRAINT store_saleorder_stock_posting_id_939235cb_fk_store_sto FOREIGN KEY (stock_posting_id) REFERENCES public.store_stockposting(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_salepayment store_salepayment_recorded_by_id_8f6e38bb_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_salepayment
    ADD CONSTRAINT store_salepayment_recorded_by_id_8f6e38bb_fk_store_user_id FOREIGN KEY (recorded_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_salepayment store_salepayment_sale_id_8772cb02_fk_store_saleorder_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_salepayment
    ADD CONSTRAINT store_salepayment_sale_id_8772cb02_fk_store_saleorder_id FOREIGN KEY (sale_id) REFERENCES public.store_saleorder(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_sourcefile store_sourcefile_dataset_version_id_70f391d5_fk_store_dat; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_sourcefile
    ADD CONSTRAINT store_sourcefile_dataset_version_id_70f391d5_fk_store_dat FOREIGN KEY (dataset_version_id) REFERENCES public.store_datasetversion(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_stockadjustment store_stockadjustmen_stock_posting_id_cc87fc02_fk_store_sto; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockadjustment
    ADD CONSTRAINT store_stockadjustmen_stock_posting_id_cc87fc02_fk_store_sto FOREIGN KEY (stock_posting_id) REFERENCES public.store_stockposting(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_stockadjustment store_stockadjustment_created_by_id_73f56a63_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockadjustment
    ADD CONSTRAINT store_stockadjustment_created_by_id_73f56a63_fk_store_user_id FOREIGN KEY (created_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_stockadjustment store_stockadjustment_posted_by_id_11d01ddf_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockadjustment
    ADD CONSTRAINT store_stockadjustment_posted_by_id_11d01ddf_fk_store_user_id FOREIGN KEY (posted_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_stockbalance store_stockbalance_variant_id_6a49866d_fk_store_variant_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockbalance
    ADD CONSTRAINT store_stockbalance_variant_id_6a49866d_fk_store_variant_id FOREIGN KEY (variant_id) REFERENCES public.store_variant(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_stockentry store_stockentry_posting_id_ea02c582_fk_store_stockposting_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockentry
    ADD CONSTRAINT store_stockentry_posting_id_ea02c582_fk_store_stockposting_id FOREIGN KEY (posting_id) REFERENCES public.store_stockposting(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_stockentry store_stockentry_variant_id_e9265a32_fk_store_variant_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockentry
    ADD CONSTRAINT store_stockentry_variant_id_e9265a32_fk_store_variant_id FOREIGN KEY (variant_id) REFERENCES public.store_variant(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_stockposting store_stockposting_posted_by_id_8e9c7785_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_stockposting
    ADD CONSTRAINT store_stockposting_posted_by_id_8e9c7785_fk_store_user_id FOREIGN KEY (posted_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_supplierorder store_supplierorder_created_by_id_a478ae7a_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_supplierorder
    ADD CONSTRAINT store_supplierorder_created_by_id_a478ae7a_fk_store_user_id FOREIGN KEY (created_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_supplierorder store_supplierorder_supplier_id_edfeb562_fk_store_supplier_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_supplierorder
    ADD CONSTRAINT store_supplierorder_supplier_id_edfeb562_fk_store_supplier_id FOREIGN KEY (supplier_id) REFERENCES public.store_supplier(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_supplierorder store_supplierorder_variant_id_52070984_fk_store_variant_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_supplierorder
    ADD CONSTRAINT store_supplierorder_variant_id_52070984_fk_store_variant_id FOREIGN KEY (variant_id) REFERENCES public.store_variant(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_user_groups store_user_groups_group_id_def3ecb1_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user_groups
    ADD CONSTRAINT store_user_groups_group_id_def3ecb1_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_user_groups store_user_groups_user_id_f76ad019_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user_groups
    ADD CONSTRAINT store_user_groups_user_id_f76ad019_fk_store_user_id FOREIGN KEY (user_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_user_user_permissions store_user_user_perm_permission_id_d9830978_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user_user_permissions
    ADD CONSTRAINT store_user_user_perm_permission_id_d9830978_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_user_user_permissions store_user_user_permissions_user_id_31a90150_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_user_user_permissions
    ADD CONSTRAINT store_user_user_permissions_user_id_31a90150_fk_store_user_id FOREIGN KEY (user_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_variant store_variant_color_id_e9bee998_fk_store_color_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_variant
    ADD CONSTRAINT store_variant_color_id_e9bee998_fk_store_color_id FOREIGN KEY (color_id) REFERENCES public.store_color(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_variant store_variant_product_id_3c4bd418_fk_store_product_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_variant
    ADD CONSTRAINT store_variant_product_id_3c4bd418_fk_store_product_id FOREIGN KEY (product_id) REFERENCES public.store_product(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_variant store_variant_size_id_7b4978ce_fk_store_size_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_variant
    ADD CONSTRAINT store_variant_size_id_7b4978ce_fk_store_size_id FOREIGN KEY (size_id) REFERENCES public.store_size(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_webguestowner store_webguestowner_account_id_97f7a692_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_webguestowner
    ADD CONSTRAINT store_webguestowner_account_id_97f7a692_fk_store_user_id FOREIGN KEY (account_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_weborder store_weborder_account_id_ebf2c6c8_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborder
    ADD CONSTRAINT store_weborder_account_id_ebf2c6c8_fk_store_user_id FOREIGN KEY (account_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_weborder store_weborder_handled_by_id_57f70f35_fk_store_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborder
    ADD CONSTRAINT store_weborder_handled_by_id_57f70f35_fk_store_user_id FOREIGN KEY (handled_by_id) REFERENCES public.store_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_weborder store_weborder_sale_id_a5987ba6_fk_store_saleorder_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborder
    ADD CONSTRAINT store_weborder_sale_id_a5987ba6_fk_store_saleorder_id FOREIGN KEY (sale_id) REFERENCES public.store_saleorder(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_weborderline store_weborderline_order_id_754877de_fk_store_weborder_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborderline
    ADD CONSTRAINT store_weborderline_order_id_754877de_fk_store_weborder_id FOREIGN KEY (order_id) REFERENCES public.store_weborder(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: store_weborderline store_weborderline_variant_id_a7b8e160_fk_store_variant_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_weborderline
    ADD CONSTRAINT store_weborderline_variant_id_a7b8e160_fk_store_variant_id FOREIGN KEY (variant_id) REFERENCES public.store_variant(id) DEFERRABLE INITIALLY DEFERRED;


--
-- PostgreSQL database dump complete
--

\unrestrict iwfVlPLCbOhYVS7MLiAxj9UC5Izjbt1ZddvE9MbGALxAFf98QIldsCxfmM7dnCQ

