from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination

_T = ExternalDataDestination.Type

# Fivetran destination service ids from
# https://github.com/fivetran/terraform-provider-fivetran/blob/main/destination-services.txt.
# A service id that is not here has no PostHog destination.
FIVETRAN_DESTINATION_TYPES: dict[str, ExternalDataDestination.Type] = {
    "snowflake": _T.SNOWFLAKE,
    "big_query": _T.BIGQUERY,
    "big_query_dts": _T.BIGQUERY,
    "managed_big_query": _T.BIGQUERY,
    "redshift": _T.REDSHIFT,
    "aurora_postgres_warehouse": _T.POSTGRES,
    "azure_postgres_warehouse": _T.POSTGRES,
    "postgres_databricks_warehouse": _T.POSTGRES,
    "postgres_gcp_warehouse": _T.POSTGRES,
    "postgres_rds_warehouse": _T.POSTGRES,
    "postgres_warehouse": _T.POSTGRES,
    "postgres_wh": _T.POSTGRES,
    "databricks": _T.DATABRICKS,
    "databricks_via_managed_data_lake": _T.DATABRICKS,
    # The Fivetran config `storage_provider` can also be ADLS or GCS, which an S3 destination cannot write to.
    "managed_data_lake": _T.S3,
}
