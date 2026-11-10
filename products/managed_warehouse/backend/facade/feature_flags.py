DATA_WAREHOUSE_SCENE_FLAG = "data-warehouse-scene"
MANAGED_TRINO_QUERY_FLAG = "managed-warehouse-trino-query"
# Either flag gives an organization the managed warehouse.
MANAGED_WAREHOUSE_ACCESS_FLAGS = (MANAGED_TRINO_QUERY_FLAG, DATA_WAREHOUSE_SCENE_FLAG)
DATA_MODELING_SHADOW_FLAG = "managed-warehouse-data-modeling-shadow"
# Evaluated for the requesting user. A user with the flag reaches Trino through the canary hostname.
MANAGED_WAREHOUSE_TRINO_CANARY_FLAG = "managed-warehouse-trino-canary"
# Marks an organization whose event, person and group backfills register through Trino.
DUCKLAKE_TRINO_REGISTRATION_FLAG = "managed-warehouse-trino-import-registration"
# Marks an organization whose data imports register through Trino. It is separate from the backfill flag so an
# organization can move backfills and data imports at different times.
DATA_IMPORTS_TRINO_REGISTRATION_FLAG = "managed-warehouse-trino-data-imports-registration"
