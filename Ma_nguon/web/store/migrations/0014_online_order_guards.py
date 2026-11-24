from importlib import import_module

from django.db import migrations


previous = import_module("store.migrations.0011_web_payment_preference")._new
snapshot = previous.replace("NEW.payment_preference,NEW.total_amount",
                            "NEW.payment_preference,NEW.delivery_address,NEW.total_amount")
snapshot = snapshot.replace("OLD.payment_preference,OLD.total_amount",
                            "OLD.payment_preference,OLD.delivery_address,OLD.total_amount")

GUARDS = """
CREATE FUNCTION public.nep_check_gateway_sale() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
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
CREATE TRIGGER nep_gateway_sale_matches BEFORE INSERT ON public.store_salepayment
 FOR EACH ROW EXECUTE FUNCTION public.nep_check_gateway_sale();

CREATE FUNCTION public.nep_check_shipment() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
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
CREATE TRIGGER nep_shipment_transition BEFORE UPDATE ON public.store_weborder
 FOR EACH ROW EXECUTE FUNCTION public.nep_check_shipment();
"""

REVERSE = """
DROP TRIGGER nep_shipment_transition ON public.store_weborder;
DROP FUNCTION public.nep_check_shipment();
DROP TRIGGER nep_gateway_sale_matches ON public.store_salepayment;
DROP FUNCTION public.nep_check_gateway_sale();
"""


class Migration(migrations.Migration):
    dependencies = [("store", "0013_web_shipment_constraints")]
    operations = [migrations.RunSQL(snapshot + GUARDS, REVERSE + previous)]

