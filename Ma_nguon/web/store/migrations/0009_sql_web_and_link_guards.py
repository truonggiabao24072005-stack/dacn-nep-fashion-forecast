"""Preserve submitted web snapshots and prevent reassignment of document rows."""
from django.db import migrations

OLD_VARIANT = r"""
CREATE OR REPLACE FUNCTION public.nep_variant_guard() RETURNS trigger
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
"""
SQL = r"""
-- Fail explicitly on pre-existing inconsistent requests; never rewrite business data.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.store_weborder o LEFT JOIN
  (SELECT order_id,count(*) n,sum(quantity::numeric*unit_price) total FROM public.store_weborderline GROUP BY order_id) l
  ON l.order_id=o.id WHERE coalesce(l.n,0) NOT BETWEEN 1 AND 30 OR o.total_amount IS DISTINCT FROM l.total) THEN
  RAISE EXCEPTION 'Existing web requests need reconciliation before migration 0009';
 END IF;
END $$;

CREATE FUNCTION public.nep_web_snapshot_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_web_request_preserved',MESSAGE='Yeu cau da gui phai duoc giu de doi chieu.';
 END IF;
 IF (NEW.id,NEW.code,NEW.request_key,NEW.owner_hash,NEW.payload_hash,NEW.customer_name,NEW.phone,NEW.note,NEW.total_amount,NEW.created_at)
 IS DISTINCT FROM (OLD.id,OLD.code,OLD.request_key,OLD.owner_hash,OLD.payload_hash,OLD.customer_name,OLD.phone,OLD.note,OLD.total_amount,OLD.created_at) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='nep_web_snapshot_immutable',MESSAGE='Thong tin va gia tri da chot cua yeu cau khong duoc ghi lai.';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.nep_web_check() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
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

CREATE FUNCTION public.nep_parent_link_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
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

CREATE TRIGGER nep_web_snapshot_guard BEFORE UPDATE OR DELETE ON public.store_weborder
 FOR EACH ROW EXECUTE FUNCTION public.nep_web_snapshot_guard();
CREATE TRIGGER nep_web_line_immutable BEFORE UPDATE OR DELETE ON public.store_weborderline
 FOR EACH ROW EXECUTE FUNCTION public.nep_immutable();
CREATE CONSTRAINT TRIGGER nep_web_check AFTER INSERT OR UPDATE ON public.store_weborder
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_web_check();
CREATE CONSTRAINT TRIGGER nep_web_check AFTER INSERT OR UPDATE OR DELETE ON public.store_weborderline
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.nep_web_check();
DO $$ DECLARE t text;BEGIN
 FOREACH t IN ARRAY ARRAY['store_saleline','store_receiptline','store_adjustmentline','store_stockbalance'] LOOP
  EXECUTE format('CREATE TRIGGER nep_parent_link_guard BEFORE UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.nep_parent_link_guard()',t);
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.nep_web_snapshot_guard(),public.nep_web_check(),public.nep_parent_link_guard() FROM PUBLIC;
""" + OLD_VARIANT.replace(
    'OR EXISTS(SELECT 1 FROM public.store_adjustmentline WHERE variant_id=OLD.id))',
    'OR EXISTS(SELECT 1 FROM public.store_adjustmentline WHERE variant_id=OLD.id)\n OR EXISTS(SELECT 1 FROM public.store_weborderline WHERE variant_id=OLD.id))')

REVERSE = r"""
DROP TRIGGER nep_web_snapshot_guard ON public.store_weborder;
DROP TRIGGER nep_web_line_immutable ON public.store_weborderline;
DROP TRIGGER nep_web_check ON public.store_weborder;
DROP TRIGGER nep_web_check ON public.store_weborderline;
DO $$ DECLARE t text;BEGIN
 FOREACH t IN ARRAY ARRAY['store_saleline','store_receiptline','store_adjustmentline','store_stockbalance'] LOOP
  EXECUTE format('DROP TRIGGER nep_parent_link_guard ON public.%I',t);
 END LOOP;
END $$;
DROP FUNCTION public.nep_web_snapshot_guard(),public.nep_web_check(),public.nep_parent_link_guard();
""" + OLD_VARIANT


class Migration(migrations.Migration):
    dependencies=[('store','0008_sql_management_views')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
