from django.conf import settings

from products.data_warehouse.backend.facade.api import ensure_bucket_exists
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention


def build_delta_table_uri(folder_path: str, resource_name: str) -> str:
    """Canonical S3 URI of a schema's Delta table.

    The writer (`DeltaTableHelper`) and readers (e.g. the fan-out warehouse parent reader)
    must agree byte-for-byte on where a table lives; both derive it here.
    """
    normalized_name = NamingConvention.normalize_identifier(resource_name)
    return f"{settings.BUCKET_URL}/{folder_path}/{normalized_name}"


def delta_storage_options() -> dict[str, str]:
    """delta-rs storage options for the data-warehouse bucket, independent of any import job — so a
    read path (e.g. the person-property backfill, the fan-out warehouse parent reader) can open a
    Delta table without constructing a full ``DeltaTableHelper`` (which carries caching, first-sync
    mutation, and corruption-repair)."""
    if settings.USE_LOCAL_SETUP:
        if (
            not settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY
            or not settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET
            or not settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION
        ):
            raise KeyError(
                "Missing env vars for data warehouse. Required vars: DATAWAREHOUSE_LOCAL_ACCESS_KEY, DATAWAREHOUSE_LOCAL_ACCESS_SECRET, DATAWAREHOUSE_LOCAL_BUCKET_REGION"
            )

        ensure_bucket_exists(
            settings.BUCKET_URL,
            settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            settings.OBJECT_STORAGE_ENDPOINT,
        )

        options = {
            "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region_name": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
            "AWS_ALLOW_HTTP": "true",
        }
    else:
        options = {}

    # Conditional puts make a clashing concurrent commit fail loudly instead of
    # clobbering _delta_log; set explicitly so a library default change can't undo it.
    options["conditional_put"] = "etag"
    if settings.DATA_WAREHOUSE_DELTA_S3_ALLOW_UNSAFE_RENAME:
        options["AWS_S3_ALLOW_UNSAFE_RENAME"] = "true"
    return options
