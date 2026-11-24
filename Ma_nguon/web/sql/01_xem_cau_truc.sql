BEGIN READ ONLY;
SELECT current_database() AS co_so_du_lieu,current_user AS tai_khoan,version() AS phien_ban;
SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user;
SELECT table_name,table_type FROM information_schema.tables WHERE table_schema='public' ORDER BY table_type,table_name;
SELECT table_name,column_name,data_type,is_nullable,numeric_precision,numeric_scale
FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position;
SELECT c.relname AS bang,x.conname AS rang_buoc,x.contype AS loai,pg_get_constraintdef(x.oid) AS dinh_nghia
FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' ORDER BY c.relname,x.conname;
SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname;
SELECT c.relname AS bang,t.tgname AS trigger,pg_get_triggerdef(t.oid) AS dinh_nghia
FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname;
COMMIT;
