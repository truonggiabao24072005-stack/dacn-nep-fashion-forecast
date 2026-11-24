"""Enforce document transitions and project customer status from persisted facts."""

from django.db import migrations


SQL = r"""
CREATE OR REPLACE FUNCTION public.nep_doc_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
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
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['store_saleorder','store_goodsreceipt','store_stockadjustment','store_documentcorrection'] LOOP
  EXECUTE format('DROP TRIGGER nep_doc_guard ON public.%I',t);
  EXECUTE format('CREATE TRIGGER nep_doc_guard BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.nep_doc_guard()',t);
 END LOOP;
END $$;

CREATE FUNCTION public.nep_web_transition_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
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
CREATE TRIGGER nep_web_transition_guard BEFORE INSERT OR UPDATE ON public.store_weborder
 FOR EACH ROW EXECUTE FUNCTION public.nep_web_transition_guard();

ALTER TABLE public.store_weborder ADD CONSTRAINT web_order_handling_consistent CHECK (
 (status='PENDING' AND handled_by_id IS NULL AND handled_at IS NULL AND reason='' AND cancel_origin='') OR
 (status='ACCEPTED' AND handled_by_id IS NOT NULL AND handled_at IS NOT NULL AND reason='' AND cancel_origin='') OR
 (status='CANCELLED' AND handled_at IS NOT NULL AND length(btrim(reason))>0 AND
  ((cancel_origin='STAFF' AND handled_by_id IS NOT NULL) OR (cancel_origin='CUSTOMER' AND handled_by_id IS NULL)))
);

CREATE VIEW public.v_nep_yeu_cau_web AS
SELECT o.id AS yeu_cau_id,o.code AS ma_yeu_cau,o.status AS trang_thai_yeu_cau,
 o.sale_id AS don_ban_id,s.status AS trang_thai_don_ban,
 CASE
  WHEN o.status='CANCELLED' THEN 'CANCELLED'
  WHEN o.status='PENDING' THEN 'PENDING'
  WHEN s.status='CANCELLED' THEN 'SALE_CANCELLED'
  WHEN s.status='POSTED' AND EXISTS(SELECT 1 FROM public.store_documentcorrection c WHERE c.original_sale_id=s.id AND c.status='POSTED') THEN 'CORRECTED'
  WHEN s.status='POSTED' THEN 'COMPLETED'
  ELSE 'ACCEPTED'
 END AS trang_thai_thuc_hien,
 o.handled_by_id AS nguoi_xu_ly_id,o.handled_at AS xu_ly_luc,o.cancel_origin AS ben_huy,o.reason AS ly_do
FROM public.store_weborder o LEFT JOIN public.store_saleorder s ON s.id=o.sale_id;

CREATE FUNCTION public.nep_web_lifecycle(request_id uuid) RETURNS text
LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT trang_thai_thuc_hien FROM public.v_nep_yeu_cau_web WHERE yeu_cau_id=request_id
$$;
REVOKE ALL ON FUNCTION public.nep_web_transition_guard() FROM PUBLIC;
"""

REVERSE = r"""
DROP FUNCTION public.nep_web_lifecycle(uuid);
DROP VIEW public.v_nep_yeu_cau_web;
ALTER TABLE public.store_weborder DROP CONSTRAINT web_order_handling_consistent;
DROP TRIGGER nep_web_transition_guard ON public.store_weborder;
DROP FUNCTION public.nep_web_transition_guard();
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['store_saleorder','store_goodsreceipt','store_stockadjustment','store_documentcorrection'] LOOP
  EXECUTE format('DROP TRIGGER nep_doc_guard ON public.%I',t);
  EXECUTE format('CREATE TRIGGER nep_doc_guard BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.nep_doc_guard()',t);
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION public.nep_doc_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF OLD.status='POSTED' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_posted_document_immutable',MESSAGE='Chung tu da ghi so phai duoc giu nguyen.';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("store", "0009_sql_web_and_link_guards")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
