import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Optional

import s3fs
import pandas as pd

from posthog.models.team import Team
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    XDIST_SUFFIX,
)

from products.warehouse_sources.backend.facade.contracts import SyncedWarehouseTable
from products.warehouse_sources.backend.facade.hogql import CLICKHOUSE_HOGQL_MAPPING, clean_type
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
    WarehouseColumnAnnotation,
)
from products.warehouse_sources.backend.facade.types import (
    ExternalDataSourceType,
    WarehouseColumnAnnotationDescriptionSource,
)

# ClickHouse runs in docker-compose and reaches object storage by its service name. OBJECT_STORAGE_ENDPOINT is the
# address for this process, and a localhost address there would make ClickHouse connect to itself.
_CLICKHOUSE_OBJECT_STORAGE_ENDPOINT = "http://objectstorage:19000"


def create_data_warehouse_table_from_csv(
    csv_path: Path,
    table_name: str,
    table_columns: Mapping[str, str | Mapping[str, str | bool]],
    test_bucket: str,
    team: Team,
    *,
    source: Optional[ExternalDataSource] = None,
    credential: Optional[DataWarehouseCredential] = None,
    source_prefix: Optional[str] = None,
):
    if not csv_path.exists():
        raise FileNotFoundError(f"Test data file not found at {csv_path}")

    # Initialize S3 filesystem
    if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_SECRET_ACCESS_KEY:
        raise Exception("Missing S3 credentials")

    fs = s3fs.S3FileSystem(
        client_kwargs={
            "region_name": "us-east-1",
            "endpoint_url": OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
        },
    )

    df = pd.read_csv(csv_path)

    # Append XDIST_SUFFIX to test bucket if it exists
    test_bucket = test_bucket + XDIST_SUFFIX

    # Guarantee prefix is valid
    if source_prefix is None:
        source_prefix = "posthog_test_"
    table_name = f"{source_prefix}{table_name}"

    # Write CSV directly to S3
    folder = f"{OBJECT_STORAGE_BUCKET}/{test_bucket}/{table_name}"
    path_to_s3_object = f"{folder}/data.csv"
    with fs.open(path_to_s3_object, "wb", blocksize=None) as f:
        df.to_csv(f, index=False)

    if source is None:
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix=source_prefix,
        )

    if credential is None:
        credential = DataWarehouseCredential.objects.create(
            team=team,
            access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
            access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        )

    if all(isinstance(value, str) for value in table_columns.values()):
        normalized_columns: dict[str, dict[str, str | bool]] = {}
        for key, value in table_columns.items():
            assert isinstance(value, str)
            normalized_columns[str(key)] = {
                "hogql": CLICKHOUSE_HOGQL_MAPPING[clean_type(value)].__name__,
                "clickhouse": value,
                "valid": True,
            }
        table_columns = normalized_columns

    table = DataWarehouseTable.objects.create(
        name=table_name,
        format=DataWarehouseTable.TableFormat.CSVWithNames,
        team=team,
        external_data_source=source,
        credential=credential,
        url_pattern=f"http://host.docker.internal:19000/{folder}/*.csv",
        columns=table_columns,
        options={"csv_allow_double_quotes": True},
    )

    # This should, in theory, be called in the test tear down
    # to get rid of the test data from S3
    def cleanUp():
        try:
            fs.rm(folder, recursive=True)
        except:
            pass

    return (table, source, credential, df, cleanUp)


def create_synced_table_from_rows(
    team: Team,
    *,
    source_type: ExternalDataSourceType,
    schema_name: str,
    table_name: str,
    columns: Mapping[str, Mapping[str, str | bool]],
    rows: Sequence[Sequence[object]],
    descriptions: Mapping[str, str],
    test_bucket: str,
    description_source: WarehouseColumnAnnotationDescriptionSource = WarehouseColumnAnnotationDescriptionSource.CANONICAL,
) -> SyncedWarehouseTable:
    """Install the state a completed source sync leaves: rows in object storage, the source, schema and table rows,
    and the table's annotations. ``""`` in ``descriptions`` is the table-level one.
    """
    access_key, access_secret = OBJECT_STORAGE_ACCESS_KEY_ID, OBJECT_STORAGE_SECRET_ACCESS_KEY
    if not access_key or not access_secret:
        raise Exception("Missing S3 credentials")

    folder = f"{OBJECT_STORAGE_BUCKET}/{test_bucket}{XDIST_SUFFIX}/team_{team.id}/{table_name}"
    fs = s3fs.S3FileSystem(
        client_kwargs={
            "region_name": "us-east-1",
            "endpoint_url": OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": access_secret,
        },
    )
    with fs.open(f"{folder}/data.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)

    source = ExternalDataSource.objects.create(
        team=team,
        source_id=f"{schema_name}_source",
        connection_id=f"{schema_name}_connection",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=source_type,
    )
    credential = DataWarehouseCredential.objects.create(team=team, access_key=access_key, access_secret=access_secret)
    table = DataWarehouseTable.objects.create(
        team=team,
        name=table_name,
        format=DataWarehouseTable.TableFormat.CSVWithNames,
        external_data_source=source,
        credential=credential,
        url_pattern=f"{_CLICKHOUSE_OBJECT_STORAGE_ENDPOINT}/{folder}/*.csv",
        columns=columns,
    )
    ExternalDataSchema.objects.create(
        team=team,
        name=schema_name,
        source=source,
        table=table,
        status=ExternalDataSchema.Status.COMPLETED,
        initial_sync_complete=True,
    )
    for column_name, description in descriptions.items():
        WarehouseColumnAnnotation.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name=column_name,
            description=description,
            description_source=description_source,
            is_user_edited=description_source == WarehouseColumnAnnotationDescriptionSource.USER_EDITED,
        )
    return SyncedWarehouseTable(table_id=table.id, name=table.name)
