from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motherduck import (
    MotherduckSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck import (
    MOTHERDUCK_ERROR_CLASSES,
    MotherDuckConnectionError,
    MotherDuckImplementation,
    connect,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    import duckdb

_MOTHERDUCK_IMPLEMENTATION = MotherDuckImplementation()


@SourceRegistry.register
class MotherduckSource(SQLSource[MotherduckSourceConfig]):
    # MotherDuck speaks the DuckDB wire protocol through the `duckdb` client, which carries no
    # vendor API version of its own.
    api_docs_url = "https://motherduck.com/docs/"

    @property
    def get_implementation(self) -> MotherDuckImplementation:
        return _MOTHERDUCK_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOTHERDUCK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MOTHERDUCK,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql", "duckdb", "md"],
            label="MotherDuck",
            caption=(
                "Enter your MotherDuck access token to query or pull your MotherDuck tables into the "
                "PostHog Data warehouse. Create an access token in your MotherDuck account settings. "
                "Leave the database blank to connect to every database in the account. Connections are "
                "opened read-only, so PostHog never modifies your data."
            ),
            iconPath="/static/services/motherduck.png",
            docsUrl="https://posthog.com/docs/cdp/sources/motherduck",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to connect to all databases",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to import all schemas",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **self.default_non_retryable_errors(),
            "Catalog Error": "A database, schema, or table this source syncs no longer exists in MotherDuck, or your access token lost access to it. Check that it still exists, then resync.",
            "Binder Error": "A column this source syncs no longer exists in MotherDuck. Reset the table so we pick up its new shape, then resync.",
            "Invalid Input Error": "MotherDuck rejected the connection details. Check the database name and access token, then resync.",
            "Invalid MotherDuck token": None,
            "UNAUTHENTICATED": "Your MotherDuck token is invalid or expired. Generate a new access token and reconnect.",
        }

    @staticmethod
    def normalized_database(config: MotherduckSourceConfig) -> str | None:
        """The configured database, or None when the source spans the whole account."""
        return (config.database or "").strip() or None

    @contextmanager
    def direct_query_connection(self, config: MotherduckSourceConfig) -> Iterator["duckdb.DuckDBPyConnection"]:
        """Open a read-only connection for a single direct (HogQL) query.

        Connection construction is an internal detail of the source; the direct-SQL adapter
        drives queries through this method rather than importing the driver helpers.
        """
        connection = connect(config.access_token, self.normalized_database(config))
        try:
            yield connection
        finally:
            connection.close()

    def validate_credentials(
        self,
        config: MotherduckSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.access_token:
            return False, "Missing required parameter: access token"

        try:
            self.get_schemas(config, team_id)
        except MotherDuckConnectionError as e:
            return False, str(e)
        except ValueError as e:
            # Raised by `build_motherduck_connection_string` for a database name we won't put in
            # the connection string; the message already names the offending value.
            return False, str(e)
        except Exception as e:
            error_msg = str(e)
            if "token" in error_msg.lower():
                return (
                    False,
                    "MotherDuck rejected the access token. Check that the token is correct and has not expired.",
                )
            for key, value in MOTHERDUCK_ERROR_CLASSES.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, "Could not connect to MotherDuck. Please check all connection details are valid."

        return True, None
