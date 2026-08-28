from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.hogql.database.s3_table import S3Table

from products.managed_warehouse.backend.client import _object_storage_secrets_for_database
from products.managed_warehouse.backend.facade.contracts import DuckLakeAzureSecret, DuckLakeS3Secret


class TestSelfManagedObjectStorageSecrets:
    @parameterized.expand(["Parquet", "CSV", "CSVWithNames", "JSONEachRow", "Delta"])
    def test_supported_format_gets_a_secret(self, table_format: str) -> None:
        database = MagicMock()
        database.get_warehouse_table_names.return_value = ["orders"]
        database.get_table.return_value = S3Table(
            name="orders",
            format=table_format,
            url="https://my-bucket.s3.amazonaws.com/data/source",
            access_key="access-key",
            access_secret="access-secret",
            table_id="01234567-89ab-cdef-0123-456789abcdef",
            fields={},
        )

        secrets = _object_storage_secrets_for_database(database)

        assert len(secrets) == 1
        assert isinstance(secrets[0], DuckLakeS3Secret)
        assert secrets[0].key_id == "access-key"
        assert secrets[0].scope == "s3://my-bucket/data/source"

    def test_invalid_azure_credentials_get_no_secret(self) -> None:
        database = MagicMock()
        database.get_warehouse_table_names.return_value = ["orders"]
        database.get_table.return_value = S3Table(
            name="orders",
            format="Parquet",
            url="https://account.blob.core.windows.net/container/data/*.parquet",
            access_key="account",
            access_secret="ZmFrZQ==;BlobEndpoint=http://127.0.0.1",
            table_id="01234567-89ab-cdef-0123-456789abcdef",
            fields={},
        )

        secrets = _object_storage_secrets_for_database(database)

        assert secrets == ()

    def test_valid_azure_credentials_get_an_azure_secret(self) -> None:
        database = MagicMock()
        database.get_warehouse_table_names.return_value = ["orders"]
        database.get_table.return_value = S3Table(
            name="orders",
            format="Parquet",
            url="https://account.blob.core.windows.net/container/data/*.parquet",
            access_key="account",
            access_secret="ZmFrZQ==",
            table_id="01234567-89ab-cdef-0123-456789abcdef",
            fields={},
        )

        secrets = _object_storage_secrets_for_database(database)

        assert len(secrets) == 1
        assert isinstance(secrets[0], DuckLakeAzureSecret)
        assert secrets[0].scope == "az://account.blob.core.windows.net/container/data/"
