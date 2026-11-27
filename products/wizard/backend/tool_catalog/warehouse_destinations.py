from products.warehouse_sources.backend.facade.models import ExternalDataDestination
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

DestinationType = ExternalDataDestination.Type

# Tools that are also an analytics warehouse PostHog can send data to, keyed by tool kind.
# Postgres is left out: in a codebase it is almost always the app's own database.
WAREHOUSE_DESTINATION_BY_KIND: dict[str, str] = {
    ExternalDataSourceType.BIGQUERY.value: DestinationType.BIGQUERY.value,
    ExternalDataSourceType.SNOWFLAKE.value: DestinationType.SNOWFLAKE.value,
    ExternalDataSourceType.REDSHIFT.value: DestinationType.REDSHIFT.value,
    ExternalDataSourceType.DATABRICKS.value: DestinationType.DATABRICKS.value,
    ExternalDataSourceType.AMAZONS3.value: DestinationType.S3.value,
    ExternalDataSourceType.AZUREBLOB.value: DestinationType.AZURE_BLOB.value,
}

# The catalog advertises every destination except PostHog's own.
CATALOG_DESTINATION_CHOICES: list[tuple[str, str]] = [
    (value, str(label)) for value, label in DestinationType.choices if value != DestinationType.POSTHOG_WAREHOUSE.value
]


def warehouse_destination_type(kind: str) -> str | None:
    return WAREHOUSE_DESTINATION_BY_KIND.get(kind)
