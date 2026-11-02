DATA_WAREHOUSE_SCENE_FLAG = "data-warehouse-scene"
MANAGED_TRINO_QUERY_FLAG = "managed-warehouse-trino-query"
# Either flag gives an organization the managed warehouse.
MANAGED_WAREHOUSE_ACCESS_FLAGS = (MANAGED_TRINO_QUERY_FLAG, DATA_WAREHOUSE_SCENE_FLAG)
DATA_MODELING_SHADOW_FLAG = "managed-warehouse-data-modeling-shadow"
# Marks an organization whose warehouse has no duckgres, so its data imports and backfills register through Trino.
DUCKLAKE_TRINO_REGISTRATION_FLAG = "managed-warehouse-trino-import-registration"
