from django.db import migrations

FORWARD = """
CREATE FUNCTION public.nep_check_supplier_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
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

CREATE TRIGGER nep_supplier_receipt_guard BEFORE INSERT OR UPDATE ON public.store_goodsreceipt
FOR EACH ROW EXECUTE FUNCTION public.nep_check_supplier_receipt();

CREATE UNIQUE INDEX nep_supplier_delivery_reference ON public.store_goodsreceipt (supplier_order_id, delivery_reference)
WHERE supplier_order_id IS NOT NULL;
"""
REVERSE = """
DROP INDEX public.nep_supplier_delivery_reference;
DROP TRIGGER nep_supplier_receipt_guard ON public.store_goodsreceipt;
DROP FUNCTION public.nep_check_supplier_receipt();
"""


class Migration(migrations.Migration):
    dependencies = [("store", "0017_pickup_and_supplier_orders")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

