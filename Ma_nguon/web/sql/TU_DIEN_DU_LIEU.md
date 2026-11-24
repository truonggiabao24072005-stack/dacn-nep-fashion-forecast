# Từ điển dữ liệu PostgreSQL

Sinh từ information_schema và pg_catalog của cơ sở dữ liệu đang cài. Không chứa giá trị bản ghi hoặc mật khẩu. Xem README.md để quản lý bằng SQL.

## auth_group — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int4 | NO | 32 bit |
| name | varchar | NO | 150 |

Ràng buộc:

- `auth_group_name_key`: `UNIQUE (name)`
- `auth_group_pkey`: `PRIMARY KEY (id)`

## auth_group_permissions — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| group_id | int4 | NO | 32 bit |
| permission_id | int4 | NO | 32 bit |

Ràng buộc:

- `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm`: `FOREIGN KEY (permission_id) REFERENCES auth_permission(id) DEFERRABLE INITIALLY DEFERRED`
- `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id`: `FOREIGN KEY (group_id) REFERENCES auth_group(id) DEFERRABLE INITIALLY DEFERRED`
- `auth_group_permissions_group_id_permission_id_0cd325b0_uniq`: `UNIQUE (group_id, permission_id)`
- `auth_group_permissions_pkey`: `PRIMARY KEY (id)`

## auth_permission — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int4 | NO | 32 bit |
| name | varchar | NO | 255 |
| content_type_id | int4 | NO | 32 bit |
| codename | varchar | NO | 100 |

Ràng buộc:

- `auth_permission_content_type_id_2f476e4b_fk_django_co`: `FOREIGN KEY (content_type_id) REFERENCES django_content_type(id) DEFERRABLE INITIALLY DEFERRED`
- `auth_permission_content_type_id_codename_01ab375a_uniq`: `UNIQUE (content_type_id, codename)`
- `auth_permission_pkey`: `PRIMARY KEY (id)`

## django_content_type — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int4 | NO | 32 bit |
| app_label | varchar | NO | 100 |
| model | varchar | NO | 100 |

Ràng buộc:

- `django_content_type_app_label_model_76bd3d3b_uniq`: `UNIQUE (app_label, model)`
- `django_content_type_pkey`: `PRIMARY KEY (id)`

## django_migrations — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| app | varchar | NO | 255 |
| name | varchar | NO | 255 |
| applied | timestamptz | NO |  |

Ràng buộc:

- `django_migrations_pkey`: `PRIMARY KEY (id)`

## django_session — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| session_key | varchar | NO | 40 |
| session_data | text | NO |  |
| expire_date | timestamptz | NO |  |

Ràng buộc:

- `django_session_pkey`: `PRIMARY KEY (session_key)`

## store_adjustmentline — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| expected_qty | int4 | NO | 32 bit |
| expected_version | int4 | NO | 32 bit |
| counted_qty | int4 | NO | 32 bit |
| adjustment_id | int8 | NO | 64 bit |
| variant_id | int8 | NO | 64 bit |

Ràng buộc:

- `adjustment_sku_unique`: `UNIQUE (adjustment_id, variant_id)`
- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_adjustmentline_adjustment_id_b4e7d990_fk_store_sto`: `FOREIGN KEY (adjustment_id) REFERENCES store_stockadjustment(id) DEFERRABLE INITIALLY DEFERRED`
- `store_adjustmentline_counted_qty_check`: `CHECK ((counted_qty >= 0))`
- `store_adjustmentline_expected_qty_check`: `CHECK ((expected_qty >= 0))`
- `store_adjustmentline_expected_version_check`: `CHECK ((expected_version >= 0))`
- `store_adjustmentline_pkey`: `PRIMARY KEY (id)`
- `store_adjustmentline_variant_id_5dc6d51a_fk_store_variant_id`: `FOREIGN KEY (variant_id) REFERENCES store_variant(id) DEFERRABLE INITIALLY DEFERRED`

## store_auditevent — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| action | varchar | NO | 60 |
| object_type | varchar | NO | 60 |
| object_id | varchar | NO | 80 |
| changed_fields | jsonb | NO |  |
| reason | text | NO |  |
| occurred_at | timestamptz | NO |  |
| actor_id | int8 | YES | 64 bit |

Ràng buộc:

- `store_auditevent_actor_id_0a24d0ec_fk_store_user_id`: `FOREIGN KEY (actor_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_auditevent_pkey`: `PRIMARY KEY (id)`

## store_brand — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 80 |
| name | varchar | NO | 200 |
| is_active | bool | NO |  |
| version | int4 | NO | 32 bit |

Ràng buộc:

- `store_brand_code_key`: `UNIQUE (code)`
- `store_brand_pkey`: `PRIMARY KEY (id)`
- `store_brand_version_check`: `CHECK ((version >= 0))`

## store_category — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 80 |
| name | varchar | NO | 200 |
| is_active | bool | NO |  |
| version | int4 | NO | 32 bit |

Ràng buộc:

- `store_category_code_key`: `UNIQUE (code)`
- `store_category_pkey`: `PRIMARY KEY (id)`
- `store_category_version_check`: `CHECK ((version >= 0))`

## store_color — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 80 |
| name | varchar | NO | 200 |
| is_active | bool | NO |  |
| version | int4 | NO | 32 bit |

Ràng buộc:

- `store_color_code_key`: `UNIQUE (code)`
- `store_color_pkey`: `PRIMARY KEY (id)`
- `store_color_version_check`: `CHECK ((version >= 0))`

## store_customer — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 80 |
| name | varchar | NO | 200 |
| is_active | bool | NO |  |
| version | int4 | NO | 32 bit |
| phone | varchar | NO | 25 |
| note | text | NO |  |

Ràng buộc:

- `store_customer_code_key`: `UNIQUE (code)`
- `store_customer_pkey`: `PRIMARY KEY (id)`
- `store_customer_version_check`: `CHECK ((version >= 0))`

## store_customerloginattempt — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| key | varchar | NO | 64 |
| failures | int4 | NO | 32 bit |
| window_start | timestamptz | NO |  |

Ràng buộc:

- `store_customerloginattempt_failures_check`: `CHECK ((failures >= 0))`
- `store_customerloginattempt_pkey`: `PRIMARY KEY (key)`

## store_customerprofile — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| phone | varchar | NO | 25 |
| user_id | int8 | NO | 64 bit |

Ràng buộc:

- `store_customerprofile_pkey`: `PRIMARY KEY (id)`
- `store_customerprofile_user_id_114129a5_fk_store_user_id`: `FOREIGN KEY (user_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_customerprofile_user_id_key`: `UNIQUE (user_id)`

## store_datasetversion — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 50 |
| source_type | varchar | NO | 12 |
| manifest_hash | varchar | NO | 64 |
| coverage_start | date | NO |  |
| coverage_end | date | NO |  |
| scope_definition | jsonb | NO |  |
| cleaning_config | jsonb | NO |  |
| status | varchar | NO | 12 |
| created_by_id | int8 | NO | 64 bit |

Ràng buộc:

- `store_datasetversion_code_key`: `UNIQUE (code)`
- `store_datasetversion_created_by_id_8d6f9fde_fk_store_user_id`: `FOREIGN KEY (created_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_datasetversion_pkey`: `PRIMARY KEY (id)`

## store_documentcorrection — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 30 |
| status | varchar | NO | 12 |
| version | int4 | NO | 32 bit |
| posted_at | timestamptz | YES |  |
| cancel_reason | text | NO |  |
| reason | text | NO |  |
| evidence | text | NO |  |
| goods_recovered_ack | bool | NO |  |
| financial_ack | bool | NO |  |
| amount_snapshot | numeric | NO | precision=18, scale=0 |
| created_by_id | int8 | NO | 64 bit |
| posted_by_id | int8 | YES | 64 bit |
| original_receipt_id | int8 | YES | 64 bit |
| original_sale_id | int8 | YES | 64 bit |
| stock_posting_id | int8 | YES | 64 bit |

Ràng buộc:

- `correction_one_original`: `CHECK ((((original_receipt_id IS NULL) AND (original_sale_id IS NOT NULL)) OR ((original_receipt_id IS NOT NULL) AND (original_sale_id IS NULL))))`
- `documentcorrection_state_consistent`: `CHECK ((((posted_at IS NOT NULL) AND (posted_by_id IS NOT NULL) AND ((status)::text = 'POSTED'::text) AND (stock_posting_id IS NOT NULL)) OR ((posted_at IS NULL) AND (posted_by_id IS NULL) AND ((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[])) AND (stock_posting_id IS NULL))))`
- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_documentcorrec_created_by_id_2f11a6f1_fk_store_use`: `FOREIGN KEY (created_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_documentcorrec_original_receipt_id_af6d9fd3_fk_store_goo`: `FOREIGN KEY (original_receipt_id) REFERENCES store_goodsreceipt(id) DEFERRABLE INITIALLY DEFERRED`
- `store_documentcorrec_original_sale_id_f559424f_fk_store_sal`: `FOREIGN KEY (original_sale_id) REFERENCES store_saleorder(id) DEFERRABLE INITIALLY DEFERRED`
- `store_documentcorrec_stock_posting_id_a5f1c743_fk_store_sto`: `FOREIGN KEY (stock_posting_id) REFERENCES store_stockposting(id) DEFERRABLE INITIALLY DEFERRED`
- `store_documentcorrection_code_key`: `UNIQUE (code)`
- `store_documentcorrection_pkey`: `PRIMARY KEY (id)`
- `store_documentcorrection_posted_by_id_f47a5262_fk_store_user_id`: `FOREIGN KEY (posted_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_documentcorrection_stock_posting_id_key`: `UNIQUE (stock_posting_id)`
- `store_documentcorrection_version_check`: `CHECK ((version >= 0))`

## store_experiment — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| target_definition | jsonb | NO |  |
| eligibility_policy | jsonb | NO |  |
| split_config | jsonb | NO |  |
| feature_spec | jsonb | NO |  |
| model_configs | jsonb | NO |  |
| random_seed | int4 | NO | 32 bit |
| status | varchar | NO | 12 |
| dataset_version_id | int8 | NO | 64 bit |

Ràng buộc:

- `nep_forecast_guard`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_experiment_dataset_version_id_2d6af2f7_fk_store_dat`: `FOREIGN KEY (dataset_version_id) REFERENCES store_datasetversion(id) DEFERRABLE INITIALLY DEFERRED`
- `store_experiment_pkey`: `PRIMARY KEY (id)`

## store_externalskumap — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| external_product_id | varchar | NO | 100 |
| evidence | text | NO |  |
| verified_by_id | int8 | YES | 64 bit |
| forecast_unit_id | int8 | NO | 64 bit |
| internal_variant_id | int8 | YES | 64 bit |

Ràng buộc:

- `external_map_unique`: `UNIQUE (forecast_unit_id, external_product_id)`
- `store_externalskumap_forecast_unit_id_62d72d73_fk_store_for`: `FOREIGN KEY (forecast_unit_id) REFERENCES store_forecastunit(id) DEFERRABLE INITIALLY DEFERRED`
- `store_externalskumap_internal_variant_id_3cab8280_fk_store_var`: `FOREIGN KEY (internal_variant_id) REFERENCES store_variant(id) DEFERRABLE INITIALLY DEFERRED`
- `store_externalskumap_pkey`: `PRIMARY KEY (id)`
- `store_externalskumap_verified_by_id_ed3f21b0_fk_store_user_id`: `FOREIGN KEY (verified_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`

## store_forecastrun — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| cutoff_month | date | NO |  |
| target_month | date | NO |  |
| scope_key | varchar | NO | 100 |
| status | varchar | NO | 12 |
| started_at | timestamptz | NO |  |
| completed_at | timestamptz | YES |  |
| model_result_id | int8 | NO | 64 bit |

Ràng buộc:

- `nep_forecast_guard`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_forecastrun_model_result_id_e47d75e4_fk_store_mod`: `FOREIGN KEY (model_result_id) REFERENCES store_modelresult(id) DEFERRABLE INITIALLY DEFERRED`
- `store_forecastrun_pkey`: `PRIMARY KEY (id)`

## store_forecastunit — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| external_key | varchar | NO | 100 |
| label | varchar | NO | 200 |
| granularity | varchar | NO | 10 |
| unit | varchar | NO | 20 |
| scope_key | varchar | NO | 100 |
| mapping_status | varchar | NO | 12 |
| mapping_evidence | text | NO |  |
| dataset_version_id | int8 | NO | 64 bit |
| internal_product_id | int8 | YES | 64 bit |

Ràng buộc:

- `forecast_unit_unique`: `UNIQUE (dataset_version_id, external_key)`
- `nep_forecast_guard`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_forecastunit_dataset_version_id_b06ee565_fk_store_dat`: `FOREIGN KEY (dataset_version_id) REFERENCES store_datasetversion(id) DEFERRABLE INITIALLY DEFERRED`
- `store_forecastunit_internal_product_id_0366b7f6_fk_store_pro`: `FOREIGN KEY (internal_product_id) REFERENCES store_product(id) DEFERRABLE INITIALLY DEFERRED`
- `store_forecastunit_pkey`: `PRIMARY KEY (id)`

## store_forecastvalue — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| raw_value | numeric | YES | precision=18, scale=4 |
| nonnegative_value | numeric | YES | precision=18, scale=4 |
| result_status | varchar | NO | 20 |
| forecast_unit_id | int8 | NO | 64 bit |
| run_id | int8 | NO | 64 bit |

Ràng buộc:

- `forecast_nonnegative`: `CHECK ((((nonnegative_value >= (0)::numeric) AND (nonnegative_value < ('100000000000000'::bigint)::numeric)) OR (nonnegative_value IS NULL)))`
- `forecast_raw_finite`: `CHECK (((raw_value IS NULL) OR ((raw_value > ('-100000000000000'::bigint)::numeric) AND (raw_value < ('100000000000000'::bigint)::numeric))))`
- `forecast_value_unique`: `UNIQUE (run_id, forecast_unit_id)`
- `nep_forecast_guard`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_forecastvalue_forecast_unit_id_2b236267_fk_store_for`: `FOREIGN KEY (forecast_unit_id) REFERENCES store_forecastunit(id) DEFERRABLE INITIALLY DEFERRED`
- `store_forecastvalue_pkey`: `PRIMARY KEY (id)`
- `store_forecastvalue_run_id_3b0f48d8_fk_store_forecastrun_id`: `FOREIGN KEY (run_id) REFERENCES store_forecastrun(id) DEFERRABLE INITIALLY DEFERRED`
- `valid_forecast_has_value`: `CHECK (((NOT ((result_status)::text = 'VALID'::text)) OR (nonnegative_value IS NOT NULL)))`

## store_goodsreceipt — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 30 |
| status | varchar | NO | 12 |
| version | int4 | NO | 32 bit |
| posted_at | timestamptz | YES |  |
| cancel_reason | text | NO |  |
| supplier_name_snapshot | varchar | NO | 200 |
| delivery_reference | varchar | NO | 100 |
| total_amount | numeric | NO | precision=18, scale=0 |
| note | text | NO |  |
| created_by_id | int8 | NO | 64 bit |
| posted_by_id | int8 | YES | 64 bit |
| stock_posting_id | int8 | YES | 64 bit |
| supplier_id | int8 | NO | 64 bit |

Ràng buộc:

- `goodsreceipt_state_consistent`: `CHECK ((((posted_at IS NOT NULL) AND (posted_by_id IS NOT NULL) AND ((status)::text = 'POSTED'::text) AND (stock_posting_id IS NOT NULL)) OR ((posted_at IS NULL) AND (posted_by_id IS NULL) AND ((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[])) AND (stock_posting_id IS NULL))))`
- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `receipt_total_valid`: `CHECK (((total_amount >= (0)::numeric) AND (total_amount < ('1000000000000000000'::bigint)::numeric)))`
- `store_goodsreceipt_code_key`: `UNIQUE (code)`
- `store_goodsreceipt_created_by_id_6e6a1136_fk_store_user_id`: `FOREIGN KEY (created_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_goodsreceipt_pkey`: `PRIMARY KEY (id)`
- `store_goodsreceipt_posted_by_id_a30ccad3_fk_store_user_id`: `FOREIGN KEY (posted_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_goodsreceipt_stock_posting_id_18769dc4_fk_store_sto`: `FOREIGN KEY (stock_posting_id) REFERENCES store_stockposting(id) DEFERRABLE INITIALLY DEFERRED`
- `store_goodsreceipt_stock_posting_id_key`: `UNIQUE (stock_posting_id)`
- `store_goodsreceipt_supplier_id_46355758_fk_store_supplier_id`: `FOREIGN KEY (supplier_id) REFERENCES store_supplier(id) DEFERRABLE INITIALLY DEFERRED`
- `store_goodsreceipt_version_check`: `CHECK ((version >= 0))`

## store_modelresult — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| method | varchar | NO | 20 |
| selected_on_validation | bool | NO |  |
| validation_metrics | jsonb | NO |  |
| test_metrics | jsonb | NO |  |
| scored_pair_manifest | jsonb | NO |  |
| artifact_path | text | NO |  |
| artifact_hash | varchar | NO | 64 |
| experiment_id | int8 | NO | 64 bit |

Ràng buộc:

- `experiment_method_unique`: `UNIQUE (experiment_id, method)`
- `nep_forecast_guard`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_modelresult_experiment_id_718c9aee_fk_store_experiment_id`: `FOREIGN KEY (experiment_id) REFERENCES store_experiment(id) DEFERRABLE INITIALLY DEFERRED`
- `store_modelresult_pkey`: `PRIMARY KEY (id)`

## store_monthlysales — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| month | date | NO |  |
| positive_qty | numeric | NO | precision=18, scale=4 |
| negative_qty_abs | numeric | NO | precision=18, scale=4 |
| net_qty | numeric | NO | precision=18, scale=4 |
| target_qty | numeric | YES | precision=18, scale=4 |
| observation_status | varchar | NO | 15 |
| source_row_count | int4 | NO | 32 bit |
| forecast_unit_id | int8 | NO | 64 bit |

Ràng buộc:

- `monthly_first_day`: `CHECK ((EXTRACT(day FROM month) = (1)::numeric))`
- `monthly_net_reconciles`: `CHECK (((net_qty = (positive_qty - negative_qty_abs)) AND (net_qty > ('-100000000000000'::bigint)::numeric) AND (net_qty < ('100000000000000'::bigint)::numeric)))`
- `monthly_nonnegative_flows`: `CHECK (((negative_qty_abs >= (0)::numeric) AND (negative_qty_abs < ('100000000000000'::bigint)::numeric) AND (positive_qty >= (0)::numeric) AND (positive_qty < ('100000000000000'::bigint)::numeric)))`
- `monthly_target_valid`: `CHECK (((target_qty IS NULL) OR ((target_qty >= (0)::numeric) AND (target_qty < ('100000000000000'::bigint)::numeric))))`
- `monthly_unit_unique`: `UNIQUE (forecast_unit_id, month)`
- `store_monthlysales_forecast_unit_id_76038f58_fk_store_for`: `FOREIGN KEY (forecast_unit_id) REFERENCES store_forecastunit(id) DEFERRABLE INITIALLY DEFERRED`
- `store_monthlysales_pkey`: `PRIMARY KEY (id)`
- `store_monthlysales_source_row_count_check`: `CHECK ((source_row_count >= 0))`

## store_operationrequest — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| operation | varchar | NO | 40 |
| request_key | uuid | NO |  |
| payload_hash | varchar | NO | 64 |
| result_type | varchar | NO | 40 |
| result_id | int8 | NO | 64 bit |
| completed_at | timestamptz | NO |  |
| actor_id | int8 | NO | 64 bit |

Ràng buộc:

- `operation_key_unique`: `UNIQUE (actor_id, operation, request_key)`
- `store_operationrequest_actor_id_dcd5841a_fk_store_user_id`: `FOREIGN KEY (actor_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_operationrequest_pkey`: `PRIMARY KEY (id)`

## store_product — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 80 |
| name | varchar | NO | 200 |
| is_active | bool | NO |  |
| version | int4 | NO | 32 bit |
| unit | varchar | NO | 20 |
| brand_id | int8 | NO | 64 bit |
| category_id | int8 | NO | 64 bit |

Ràng buộc:

- `store_product_brand_id_ec9e66ab_fk_store_brand_id`: `FOREIGN KEY (brand_id) REFERENCES store_brand(id) DEFERRABLE INITIALLY DEFERRED`
- `store_product_category_id_574bae65_fk_store_category_id`: `FOREIGN KEY (category_id) REFERENCES store_category(id) DEFERRABLE INITIALLY DEFERRED`
- `store_product_code_key`: `UNIQUE (code)`
- `store_product_pkey`: `PRIMARY KEY (id)`
- `store_product_version_check`: `CHECK ((version >= 0))`

## store_receiptline — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| quantity | int4 | NO | 32 bit |
| sku_snapshot | varchar | NO | 80 |
| name_snapshot | varchar | NO | 200 |
| variant_snapshot | varchar | NO | 150 |
| unit_cost | numeric | NO | precision=18, scale=0 |
| receipt_id | int8 | NO | 64 bit |
| variant_id | int8 | NO | 64 bit |

Ràng buộc:

- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `receipt_cost_nonnegative`: `CHECK (((unit_cost >= (0)::numeric) AND (unit_cost < ('1000000000000000000'::bigint)::numeric)))`
- `receipt_sku_unique`: `UNIQUE (receipt_id, variant_id)`
- `receiptline_qty_positive`: `CHECK ((quantity > 0))`
- `store_receiptline_pkey`: `PRIMARY KEY (id)`
- `store_receiptline_quantity_check`: `CHECK ((quantity >= 0))`
- `store_receiptline_receipt_id_84259751_fk_store_goodsreceipt_id`: `FOREIGN KEY (receipt_id) REFERENCES store_goodsreceipt(id) DEFERRABLE INITIALLY DEFERRED`
- `store_receiptline_variant_id_c6dfa667_fk_store_variant_id`: `FOREIGN KEY (variant_id) REFERENCES store_variant(id) DEFERRABLE INITIALLY DEFERRED`

## store_replenishmentpolicy — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| safety_stock_qty | int4 | NO | 32 bit |
| effective_from | timestamptz | NO |  |
| effective_to | timestamptz | YES |  |
| product_id | int8 | NO | 64 bit |
| updated_by_id | int8 | NO | 64 bit |

Ràng buộc:

- `store_replenishmentp_product_id_d755a517_fk_store_pro`: `FOREIGN KEY (product_id) REFERENCES store_product(id) DEFERRABLE INITIALLY DEFERRED`
- `store_replenishmentp_updated_by_id_a0a41f50_fk_store_use`: `FOREIGN KEY (updated_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_replenishmentpolicy_pkey`: `PRIMARY KEY (id)`
- `store_replenishmentpolicy_safety_stock_qty_check`: `CHECK ((safety_stock_qty >= 0))`

## store_replenishmentsuggestion — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| inventory_qty_snapshot | int4 | NO | 32 bit |
| inventory_versions | jsonb | NO |  |
| inventory_as_of | timestamptz | NO |  |
| safety_stock_snapshot | int4 | NO | 32 bit |
| suggested_qty | int4 | NO | 32 bit |
| status | varchar | NO | 15 |
| forecast_value_id | int8 | NO | 64 bit |
| generated_by_id | int8 | NO | 64 bit |
| product_id | int8 | NO | 64 bit |

Ràng buộc:

- `store_replenishments_forecast_value_id_373db9cc_fk_store_for`: `FOREIGN KEY (forecast_value_id) REFERENCES store_forecastvalue(id) DEFERRABLE INITIALLY DEFERRED`
- `store_replenishments_generated_by_id_56f463c6_fk_store_use`: `FOREIGN KEY (generated_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_replenishments_product_id_c359b4ec_fk_store_pro`: `FOREIGN KEY (product_id) REFERENCES store_product(id) DEFERRABLE INITIALLY DEFERRED`
- `store_replenishmentsuggestion_inventory_qty_snapshot_check`: `CHECK ((inventory_qty_snapshot >= 0))`
- `store_replenishmentsuggestion_pkey`: `PRIMARY KEY (id)`
- `store_replenishmentsuggestion_safety_stock_snapshot_check`: `CHECK ((safety_stock_snapshot >= 0))`
- `store_replenishmentsuggestion_suggested_qty_check`: `CHECK ((suggested_qty >= 0))`

## store_saleline — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| quantity | int4 | NO | 32 bit |
| sku_snapshot | varchar | NO | 80 |
| name_snapshot | varchar | NO | 200 |
| variant_snapshot | varchar | NO | 150 |
| unit_price | numeric | NO | precision=18, scale=0 |
| sale_id | int8 | NO | 64 bit |
| variant_id | int8 | NO | 64 bit |

Ràng buộc:

- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `sale_price_positive`: `CHECK (((unit_price > (0)::numeric) AND (unit_price < ('1000000000000000000'::bigint)::numeric)))`
- `sale_sku_unique`: `UNIQUE (sale_id, variant_id)`
- `saleline_qty_positive`: `CHECK ((quantity > 0))`
- `store_saleline_pkey`: `PRIMARY KEY (id)`
- `store_saleline_quantity_check`: `CHECK ((quantity >= 0))`
- `store_saleline_sale_id_5e25b3a4_fk_store_saleorder_id`: `FOREIGN KEY (sale_id) REFERENCES store_saleorder(id) DEFERRABLE INITIALLY DEFERRED`
- `store_saleline_variant_id_f2c928f3_fk_store_variant_id`: `FOREIGN KEY (variant_id) REFERENCES store_variant(id) DEFERRABLE INITIALLY DEFERRED`

## store_saleorder — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 30 |
| status | varchar | NO | 12 |
| version | int4 | NO | 32 bit |
| posted_at | timestamptz | YES |  |
| cancel_reason | text | NO |  |
| customer_name_snapshot | varchar | NO | 200 |
| total_amount | numeric | NO | precision=18, scale=0 |
| created_by_id | int8 | NO | 64 bit |
| customer_id | int8 | YES | 64 bit |
| posted_by_id | int8 | YES | 64 bit |
| replacement_for_id | int8 | YES | 64 bit |
| stock_posting_id | int8 | YES | 64 bit |

Ràng buộc:

- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `sale_total_valid`: `CHECK (((total_amount >= (0)::numeric) AND (total_amount < ('1000000000000000000'::bigint)::numeric)))`
- `saleorder_state_consistent`: `CHECK ((((posted_at IS NOT NULL) AND (posted_by_id IS NOT NULL) AND ((status)::text = 'POSTED'::text) AND (stock_posting_id IS NOT NULL)) OR ((posted_at IS NULL) AND (posted_by_id IS NULL) AND ((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[])) AND (stock_posting_id IS NULL))))`
- `store_saleorder_code_key`: `UNIQUE (code)`
- `store_saleorder_created_by_id_0cbcc9a1_fk_store_user_id`: `FOREIGN KEY (created_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_saleorder_customer_id_8e4c266a_fk_store_customer_id`: `FOREIGN KEY (customer_id) REFERENCES store_customer(id) DEFERRABLE INITIALLY DEFERRED`
- `store_saleorder_pkey`: `PRIMARY KEY (id)`
- `store_saleorder_posted_by_id_1c5bcaca_fk_store_user_id`: `FOREIGN KEY (posted_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_saleorder_replacement_for_id_197e287a_fk_store_sal`: `FOREIGN KEY (replacement_for_id) REFERENCES store_saleorder(id) DEFERRABLE INITIALLY DEFERRED`
- `store_saleorder_stock_posting_id_939235cb_fk_store_sto`: `FOREIGN KEY (stock_posting_id) REFERENCES store_stockposting(id) DEFERRABLE INITIALLY DEFERRED`
- `store_saleorder_stock_posting_id_key`: `UNIQUE (stock_posting_id)`
- `store_saleorder_version_check`: `CHECK ((version >= 0))`

## store_salepayment — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| method | varchar | NO | 10 |
| amount | numeric | NO | precision=18, scale=0 |
| cash_received | numeric | YES | precision=18, scale=0 |
| change_amount | numeric | YES | precision=18, scale=0 |
| reference | varchar | NO | 100 |
| recorded_at | timestamptz | NO |  |
| recorded_by_id | int8 | NO | 64 bit |
| sale_id | int8 | NO | 64 bit |

Ràng buộc:

- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `payment_amount_nonnegative`: `CHECK (((amount >= (0)::numeric) AND (amount < ('1000000000000000000'::bigint)::numeric)))`
- `payment_cash_finite`: `CHECK ((((cash_received IS NULL) OR ((cash_received >= (0)::numeric) AND (cash_received < ('1000000000000000000'::bigint)::numeric))) AND ((change_amount IS NULL) OR ((change_amount >= (0)::numeric) AND (change_amount < ('1000000000000000000'::bigint)::numeric)))))`
- `payment_method_values`: `CHECK ((((cash_received >= amount) AND (cash_received IS NOT NULL) AND (change_amount = (cash_received - amount)) AND (change_amount IS NOT NULL) AND ((method)::text = 'CASH'::text)) OR ((cash_received IS NULL) AND (change_amount IS NULL) AND ((method)::text = 'TRANSFER'::text))))`
- `store_salepayment_pkey`: `PRIMARY KEY (id)`
- `store_salepayment_recorded_by_id_8f6e38bb_fk_store_user_id`: `FOREIGN KEY (recorded_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_salepayment_sale_id_8772cb02_fk_store_saleorder_id`: `FOREIGN KEY (sale_id) REFERENCES store_saleorder(id) DEFERRABLE INITIALLY DEFERRED`
- `store_salepayment_sale_id_key`: `UNIQUE (sale_id)`

## store_size — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 80 |
| name | varchar | NO | 200 |
| is_active | bool | NO |  |
| version | int4 | NO | 32 bit |

Ràng buộc:

- `store_size_code_key`: `UNIQUE (code)`
- `store_size_pkey`: `PRIMARY KEY (id)`
- `store_size_version_check`: `CHECK ((version >= 0))`

## store_sourcefile — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| relative_name | text | NO |  |
| sha256 | varchar | NO | 64 |
| row_count | int4 | NO | 32 bit |
| schema_version | varchar | NO | 30 |
| validation_status | varchar | NO | 15 |
| dataset_version_id | int8 | NO | 64 bit |

Ràng buộc:

- `source_hash_unique`: `UNIQUE (dataset_version_id, sha256)`
- `store_sourcefile_dataset_version_id_70f391d5_fk_store_dat`: `FOREIGN KEY (dataset_version_id) REFERENCES store_datasetversion(id) DEFERRABLE INITIALLY DEFERRED`
- `store_sourcefile_pkey`: `PRIMARY KEY (id)`
- `store_sourcefile_row_count_check`: `CHECK ((row_count >= 0))`

## store_stockadjustment — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 30 |
| status | varchar | NO | 12 |
| version | int4 | NO | 32 bit |
| posted_at | timestamptz | YES |  |
| cancel_reason | text | NO |  |
| kind | varchar | NO | 10 |
| reason | text | NO |  |
| source_reference | varchar | NO | 100 |
| created_by_id | int8 | NO | 64 bit |
| posted_by_id | int8 | YES | 64 bit |
| stock_posting_id | int8 | YES | 64 bit |

Ràng buộc:

- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `stockadjustment_state_consistent`: `CHECK ((((posted_at IS NOT NULL) AND (posted_by_id IS NOT NULL) AND ((status)::text = 'POSTED'::text) AND (stock_posting_id IS NOT NULL)) OR ((posted_at IS NULL) AND (posted_by_id IS NULL) AND ((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'CANCELLED'::character varying])::text[])) AND (stock_posting_id IS NULL))))`
- `store_stockadjustmen_stock_posting_id_cc87fc02_fk_store_sto`: `FOREIGN KEY (stock_posting_id) REFERENCES store_stockposting(id) DEFERRABLE INITIALLY DEFERRED`
- `store_stockadjustment_code_key`: `UNIQUE (code)`
- `store_stockadjustment_created_by_id_73f56a63_fk_store_user_id`: `FOREIGN KEY (created_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_stockadjustment_pkey`: `PRIMARY KEY (id)`
- `store_stockadjustment_posted_by_id_11d01ddf_fk_store_user_id`: `FOREIGN KEY (posted_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_stockadjustment_stock_posting_id_key`: `UNIQUE (stock_posting_id)`
- `store_stockadjustment_version_check`: `CHECK ((version >= 0))`

## store_stockbalance — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| variant_id | int8 | NO | 64 bit |
| quantity | int4 | NO | 32 bit |
| version | int4 | NO | 32 bit |
| updated_at | timestamptz | NO |  |

Ràng buộc:

- `nep_balance_check`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_stockbalance_pkey`: `PRIMARY KEY (variant_id)`
- `store_stockbalance_quantity_check`: `CHECK ((quantity >= 0))`
- `store_stockbalance_variant_id_6a49866d_fk_store_variant_id`: `FOREIGN KEY (variant_id) REFERENCES store_variant(id) DEFERRABLE INITIALLY DEFERRED`
- `store_stockbalance_version_check`: `CHECK ((version >= 0))`

## store_stockentry — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| delta | int4 | NO | 32 bit |
| variant_id | int8 | NO | 64 bit |
| posting_id | int8 | NO | 64 bit |

Ràng buộc:

- `entry_nonzero`: `CHECK ((NOT (delta = 0)))`
- `entry_sku_unique`: `UNIQUE (posting_id, variant_id)`
- `nep_balance_check`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_stockentry_pkey`: `PRIMARY KEY (id)`
- `store_stockentry_posting_id_ea02c582_fk_store_stockposting_id`: `FOREIGN KEY (posting_id) REFERENCES store_stockposting(id) DEFERRABLE INITIALLY DEFERRED`
- `store_stockentry_variant_id_e9265a32_fk_store_variant_id`: `FOREIGN KEY (variant_id) REFERENCES store_variant(id) DEFERRABLE INITIALLY DEFERRED`

## store_stockposting — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| kind | varchar | NO | 20 |
| business_key | varchar | NO | 100 |
| posted_at | timestamptz | NO |  |
| posted_by_id | int8 | NO | 64 bit |

Ràng buộc:

- `nep_check_commit`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_stockposting_business_key_key`: `UNIQUE (business_key)`
- `store_stockposting_pkey`: `PRIMARY KEY (id)`
- `store_stockposting_posted_by_id_8e9c7785_fk_store_user_id`: `FOREIGN KEY (posted_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`

## store_supplier — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| code | varchar | NO | 80 |
| name | varchar | NO | 200 |
| is_active | bool | NO |  |
| version | int4 | NO | 32 bit |
| phone | varchar | NO | 25 |
| address | text | NO |  |

Ràng buộc:

- `store_supplier_code_key`: `UNIQUE (code)`
- `store_supplier_pkey`: `PRIMARY KEY (id)`
- `store_supplier_version_check`: `CHECK ((version >= 0))`

## store_systemguard — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int2 | NO | 16 bit |
| version | int4 | NO | 32 bit |
| data_mode | varchar | NO | 12 |
| initialized_at | timestamptz | NO |  |

Ràng buộc:

- `store_systemguard_id_check`: `CHECK ((id >= 0))`
- `store_systemguard_pkey`: `PRIMARY KEY (id)`
- `store_systemguard_version_check`: `CHECK ((version >= 0))`

## store_user — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| password | varchar | NO | 128 |
| last_login | timestamptz | YES |  |
| is_superuser | bool | NO |  |
| username | varchar | NO | 150 |
| first_name | varchar | NO | 150 |
| last_name | varchar | NO | 150 |
| email | varchar | NO | 254 |
| is_staff | bool | NO |  |
| is_active | bool | NO |  |
| date_joined | timestamptz | NO |  |
| full_name | varchar | NO | 150 |
| role | varchar | NO | 12 |
| version | int4 | NO | 32 bit |
| updated_at | timestamptz | NO |  |

Ràng buộc:

- `customer_no_staff_flags`: `CHECK (((NOT ((role)::text = 'CUSTOMER'::text)) OR ((NOT is_staff) AND (NOT is_superuser))))`
- `store_user_pkey`: `PRIMARY KEY (id)`
- `store_user_username_key`: `UNIQUE (username)`
- `store_user_version_check`: `CHECK ((version >= 0))`
- `user_valid_role`: `CHECK (((role)::text = ANY ((ARRAY['ADMIN'::character varying, 'SALES'::character varying, 'WAREHOUSE'::character varying, 'CUSTOMER'::character varying])::text[])))`

## store_user_groups — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| user_id | int8 | NO | 64 bit |
| group_id | int4 | NO | 32 bit |

Ràng buộc:

- `store_user_groups_group_id_def3ecb1_fk_auth_group_id`: `FOREIGN KEY (group_id) REFERENCES auth_group(id) DEFERRABLE INITIALLY DEFERRED`
- `store_user_groups_pkey`: `PRIMARY KEY (id)`
- `store_user_groups_user_id_f76ad019_fk_store_user_id`: `FOREIGN KEY (user_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_user_groups_user_id_group_id_d5c2dca2_uniq`: `UNIQUE (user_id, group_id)`

## store_user_user_permissions — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| user_id | int8 | NO | 64 bit |
| permission_id | int4 | NO | 32 bit |

Ràng buộc:

- `store_user_user_perm_permission_id_d9830978_fk_auth_perm`: `FOREIGN KEY (permission_id) REFERENCES auth_permission(id) DEFERRABLE INITIALLY DEFERRED`
- `store_user_user_permissions_pkey`: `PRIMARY KEY (id)`
- `store_user_user_permissions_user_id_31a90150_fk_store_user_id`: `FOREIGN KEY (user_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_user_user_permissions_user_id_permission_id_bfd44b7c_uniq`: `UNIQUE (user_id, permission_id)`

## store_variant — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| sku | varchar | NO | 80 |
| selling_price | numeric | NO | precision=18, scale=0 |
| low_stock_threshold | int4 | YES | 32 bit |
| is_active | bool | NO |  |
| version | int4 | NO | 32 bit |
| color_id | int8 | NO | 64 bit |
| product_id | int8 | NO | 64 bit |
| size_id | int8 | NO | 64 bit |

Ràng buộc:

- `nep_variant_has_balance`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_variant_color_id_e9bee998_fk_store_color_id`: `FOREIGN KEY (color_id) REFERENCES store_color(id) DEFERRABLE INITIALLY DEFERRED`
- `store_variant_low_stock_threshold_check`: `CHECK ((low_stock_threshold >= 0))`
- `store_variant_pkey`: `PRIMARY KEY (id)`
- `store_variant_product_id_3c4bd418_fk_store_product_id`: `FOREIGN KEY (product_id) REFERENCES store_product(id) DEFERRABLE INITIALLY DEFERRED`
- `store_variant_size_id_7b4978ce_fk_store_size_id`: `FOREIGN KEY (size_id) REFERENCES store_size(id) DEFERRABLE INITIALLY DEFERRED`
- `store_variant_sku_key`: `UNIQUE (sku)`
- `store_variant_version_check`: `CHECK ((version >= 0))`
- `variant_combination_unique`: `UNIQUE (product_id, size_id, color_id)`
- `variant_price_nonnegative`: `CHECK (((selling_price >= (0)::numeric) AND (selling_price < ('1000000000000000000'::bigint)::numeric)))`

## store_webguestowner — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| owner_hash | varchar | NO | 64 |
| account_id | int8 | YES | 64 bit |

Ràng buộc:

- `store_webguestowner_account_id_97f7a692_fk_store_user_id`: `FOREIGN KEY (account_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_webguestowner_pkey`: `PRIMARY KEY (owner_hash)`

## store_weborder — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| created_at | timestamptz | NO |  |
| updated_at | timestamptz | NO |  |
| id | uuid | NO |  |
| code | varchar | NO | 30 |
| request_key | uuid | NO |  |
| owner_hash | varchar | NO | 64 |
| payload_hash | varchar | NO | 64 |
| customer_name | varchar | NO | 150 |
| phone | varchar | NO | 25 |
| note | varchar | NO | 1000 |
| status | varchar | NO | 12 |
| total_amount | numeric | NO | precision=18, scale=0 |
| handled_at | timestamptz | YES |  |
| reason | varchar | NO | 1000 |
| cancel_origin | varchar | NO | 10 |
| version | int4 | NO | 32 bit |
| handled_by_id | int8 | YES | 64 bit |
| sale_id | int8 | YES | 64 bit |
| account_id | int8 | YES | 64 bit |
| payment_preference | varchar | NO | 12 |

Ràng buộc:

- `nep_web_check`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_weborder_account_id_ebf2c6c8_fk_store_user_id`: `FOREIGN KEY (account_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_weborder_code_key`: `UNIQUE (code)`
- `store_weborder_handled_by_id_57f70f35_fk_store_user_id`: `FOREIGN KEY (handled_by_id) REFERENCES store_user(id) DEFERRABLE INITIALLY DEFERRED`
- `store_weborder_pkey`: `PRIMARY KEY (id)`
- `store_weborder_request_key_key`: `UNIQUE (request_key)`
- `store_weborder_sale_id_a5987ba6_fk_store_saleorder_id`: `FOREIGN KEY (sale_id) REFERENCES store_saleorder(id) DEFERRABLE INITIALLY DEFERRED`
- `store_weborder_sale_id_key`: `UNIQUE (sale_id)`
- `store_weborder_version_check`: `CHECK ((version >= 0))`
- `web_order_handling_consistent`: `CHECK (((((status)::text = 'PENDING'::text) AND (handled_by_id IS NULL) AND (handled_at IS NULL) AND ((reason)::text = ''::text) AND ((cancel_origin)::text = ''::text)) OR (((status)::text = 'ACCEPTED'::text) AND (handled_by_id IS NOT NULL) AND (handled_at IS NOT NULL) AND ((reason)::text = ''::text) AND ((cancel_origin)::text = ''::text)) OR (((status)::text = 'CANCELLED'::text) AND (handled_at IS NOT NULL) AND (length(btrim((reason)::text)) > 0) AND ((((cancel_origin)::text = 'STAFF'::text) AND (handled_by_id IS NOT NULL)) OR (((cancel_origin)::text = 'CUSTOMER'::text) AND (handled_by_id IS NULL))))))`
- `web_order_state_valid`: `CHECK ((((handled_at IS NOT NULL) AND (handled_by_id IS NOT NULL) AND (sale_id IS NOT NULL) AND ((status)::text = 'ACCEPTED'::text)) OR ((sale_id IS NULL) AND ((status)::text = ANY ((ARRAY['PENDING'::character varying, 'CANCELLED'::character varying])::text[])))))`
- `web_order_total_positive`: `CHECK (((total_amount > (0)::numeric) AND (total_amount < ('1000000000000000000'::bigint)::numeric)))`
- `web_payment_preference_valid`: `CHECK (((payment_preference)::text = ANY ((ARRAY['UNSPECIFIED'::character varying, 'CASH'::character varying, 'TRANSFER'::character varying])::text[])))`

## store_weborderline — BASE TABLE

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| id | int8 | NO | 64 bit |
| quantity | int4 | NO | 32 bit |
| unit_price | numeric | NO | precision=18, scale=0 |
| name_snapshot | varchar | NO | 200 |
| sku_snapshot | varchar | NO | 80 |
| variant_snapshot | varchar | NO | 150 |
| order_id | uuid | NO |  |
| variant_id | int8 | NO | 64 bit |

Ràng buộc:

- `nep_web_check`: `TRIGGER DEFERRABLE INITIALLY DEFERRED`
- `store_weborderline_order_id_754877de_fk_store_weborder_id`: `FOREIGN KEY (order_id) REFERENCES store_weborder(id) DEFERRABLE INITIALLY DEFERRED`
- `store_weborderline_pkey`: `PRIMARY KEY (id)`
- `store_weborderline_quantity_check`: `CHECK ((quantity >= 0))`
- `store_weborderline_variant_id_a7b8e160_fk_store_variant_id`: `FOREIGN KEY (variant_id) REFERENCES store_variant(id) DEFERRABLE INITIALLY DEFERRED`
- `web_order_line_price_positive`: `CHECK (((unit_price > (0)::numeric) AND (unit_price < ('1000000000000000000'::bigint)::numeric)))`
- `web_order_quantity_valid`: `CHECK (((quantity > 0) AND (quantity <= 99)))`
- `web_order_variant_unique`: `UNIQUE (order_id, variant_id)`

## v_nep_don_ban — VIEW

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| don_ban_id | int8 | YES | 64 bit |
| ma_don | varchar | YES | 30 |
| trang_thai | varchar | YES | 12 |
| nguoi_lap_id | int8 | YES | 64 bit |
| ghi_so_luc | timestamptz | YES |  |
| ngay_ghi_so | date | YES |  |
| so_dong | int8 | YES | 64 bit |
| so_luong | int8 | YES | 64 bit |
| tong_don | numeric | YES | precision=18, scale=0 |
| tong_dong | numeric | YES |  |
| phuong_thuc | varchar | YES | 10 |
| tien_da_ghi_nhan | numeric | YES | precision=18, scale=0 |
| chenh_lech | numeric | YES |  |

Ràng buộc:


## v_nep_du_bao — VIEW

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| ket_qua_id | int8 | YES | 64 bit |
| phien_ban_du_lieu | varchar | YES | 50 |
| loai_nguon | varchar | YES | 12 |
| trang_thai_du_lieu | varchar | YES | 12 |
| ma_nguon | varchar | YES | 100 |
| ten_hien_thi | varchar | YES | 200 |
| cap_du_bao | varchar | YES | 10 |
| don_vi | varchar | YES | 20 |
| pham_vi | varchar | YES | 100 |
| anh_xa | varchar | YES | 12 |
| ma_san_pham_noi_bo | varchar | YES | 80 |
| thang_chot | date | YES |  |
| thang_du_bao | date | YES |  |
| phuong_phap | varchar | YES | 20 |
| da_chon_bang_kiem_dinh | bool | YES |  |
| trang_thai_chay | varchar | YES | 12 |
| luong_du_bao | numeric | YES | precision=18, scale=4 |
| trang_thai_ket_qua | varchar | YES | 20 |
| sai_so_kiem_dinh | jsonb | YES |  |
| sai_so_kiem_tra | jsonb | YES |  |

Ràng buộc:


## v_nep_so_kho — VIEW

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| dong_so_id | int8 | YES | 64 bit |
| sku | varchar | YES | 80 |
| ma_san_pham | varchar | YES | 80 |
| kich_co | varchar | YES | 200 |
| mau | varchar | YES | 200 |
| loai_bien_dong | varchar | YES | 20 |
| khoa_chung_tu | varchar | YES | 100 |
| thay_doi | int4 | YES | 32 bit |
| ghi_so_luc | timestamptz | YES |  |
| nguoi_ghi_so_id | int8 | YES | 64 bit |

Ràng buộc:


## v_nep_su_kien_doanh_thu — VIEW

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| loai | text | YES |  |
| chung_tu_id | int8 | YES | 64 bit |
| ma_chung_tu | varchar | YES | 30 |
| ma_goc | varchar | YES | 30 |
| ghi_so_luc | timestamptz | YES |  |
| ngay_ghi_so | date | YES |  |
| gia_tri | numeric | YES |  |
| so_luong | int8 | YES | 64 bit |

Ràng buộc:


## v_nep_ton_kho — VIEW

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| bien_the_id | int8 | YES | 64 bit |
| ma_san_pham | varchar | YES | 80 |
| ten_san_pham | varchar | YES | 200 |
| sku | varchar | YES | 80 |
| kich_co | varchar | YES | 200 |
| mau | varchar | YES | 200 |
| don_vi | varchar | YES | 20 |
| gia_ban | numeric | YES | precision=18, scale=0 |
| ton_hien_tai | int4 | YES | 32 bit |
| ton_so_kho | int8 | YES | 64 bit |
| chenh_lech | int8 | YES | 64 bit |
| dang_ban | bool | YES |  |
| ton_ban_duoc | int4 | YES | 32 bit |
| nguong_canh_bao | int4 | YES | 32 bit |
| phien_ban_ton | int4 | YES | 32 bit |
| cap_nhat_luc | timestamptz | YES |  |

Ràng buộc:


## v_nep_yeu_cau_web — VIEW

| Cột | Kiểu PostgreSQL | Cho phép NULL | Tham số kiểu |
|---|---|---|---|
| yeu_cau_id | uuid | YES |  |
| ma_yeu_cau | varchar | YES | 30 |
| trang_thai_yeu_cau | varchar | YES | 12 |
| don_ban_id | int8 | YES | 64 bit |
| trang_thai_don_ban | varchar | YES | 12 |
| trang_thai_thuc_hien | text | YES |  |
| nguoi_xu_ly_id | int8 | YES | 64 bit |
| xu_ly_luc | timestamptz | YES |  |
| ben_huy | varchar | YES | 10 |
| ly_do | varchar | YES | 1000 |

Ràng buộc:

