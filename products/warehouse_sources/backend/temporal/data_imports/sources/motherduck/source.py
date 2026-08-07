from typing import Optional, cast

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
    MotherDuckImplementation,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MOTHERDUCK_IMPLEMENTATION = MotherDuckImplementation()

# DuckDB prefixes every error message with its stable error class ("Catalog Error:", "Binder
# Error:", …). The text after the prefix carries volatile object names, so we match the class.
MotherDuckErrors = {
    "Catalog Error": "Can't find that database or schema in MotherDuck. Check the database and schema names, then try again.",
    "Binder Error": "MotherDuck rejected the query. Check that the database and schema still contain the tables you want to sync.",
    "Invalid Input Error": "MotherDuck rejected the connection details. Check the database name and access token, then try again.",
}


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
            keywords=["sql", "duckdb"],
            label="MotherDuck",
            caption="Enter your MotherDuck access token and database name to pull your MotherDuck tables into the PostHog Data warehouse. Create an access token in your MotherDuck account settings.",
            iconPath="/static/services/motherduck.png",
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
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my_db",
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
        }

    def validate_credentials(
        self,
        config: MotherduckSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.access_token:
            return False, "Missing required parameter: access token"
        if not config.database.strip():
            return False, "Missing required parameter: database"

        try:
            self.get_schemas(config, team_id)
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
            for key, value in MotherDuckErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, "Could not connect to MotherDuck. Please check all connection details are valid."

        return True, None
