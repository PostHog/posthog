from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.databricks.databricks import (
    DatabricksImplementation,
    clean_databricks_host,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.databricks import (
    DatabricksSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_DATABRICKS_IMPLEMENTATION = DatabricksImplementation()

# Error-substring → user-facing message map used by `validate_credentials`. Databricks surfaces
# stable SQLSTATE-style error classes in brackets (e.g. `[CATALOG_NOT_FOUND]`) plus a handful of
# stable auth phrases from the Thrift/OAuth layers; the hosts, request ids, and object names around
# them are volatile, so we match the stable fragment.
DatabricksErrors = {
    "Invalid access token": "Databricks rejected the access token. Check that the personal access token is correct and has not expired or been revoked.",
    "invalid_client": "Databricks rejected the service principal credentials. Check the client ID and client secret, and that the service principal still exists.",
    "CATALOG_NOT_FOUND": "Can't find the configured catalog. Check the catalog name and that your credentials have USE CATALOG on it.",
    "NO_SUCH_CATALOG_EXCEPTION": "Can't find the configured catalog. Check the catalog name and that your credentials have USE CATALOG on it.",
    "SCHEMA_NOT_FOUND": "Can't find the configured schema. Check the schema name and that your credentials have USE SCHEMA on it.",
    "PERMISSION_DENIED": "Your Databricks credentials don't have permission to access this data. Grant USE CATALOG, USE SCHEMA, and SELECT to the connecting principal, then try again.",
    "INSUFFICIENT_PERMISSIONS": "Your Databricks credentials don't have permission to access this data. Grant USE CATALOG, USE SCHEMA, and SELECT to the connecting principal, then try again.",
    "TABLE_OR_VIEW_NOT_FOUND": "The catalog has no `information_schema` — this usually means it's a legacy `hive_metastore` catalog. The Databricks source requires a Unity Catalog catalog.",
    # Raised when the SQL warehouse referenced by the HTTP path was mistyped or deleted — a common
    # setup mistake that otherwise falls through to the generic "could not connect" message.
    "RESOURCE_DOES_NOT_EXIST": "Can't find the SQL warehouse referenced by the HTTP path. Check the HTTP path points to an existing, running SQL warehouse.",
    "nodename nor servname provided": "Can't resolve the server hostname. Check the server hostname and try again.",
    "Name or service not known": "Can't resolve the server hostname. Check the server hostname and try again.",
    "Failed to resolve": "Can't resolve the server hostname. Check the server hostname and try again.",
    "is blocked by Databricks IP ACL for workspace": "PostHog's IP address is blocked by your Databricks workspace's IP access control list. Add PostHog's IP addresses to the workspace's IP ACL, then try again.",
}


@SourceRegistry.register
class DatabricksSource(SQLSource[DatabricksSourceConfig], ValidateDatabaseHostMixin):
    api_docs_url = "https://docs.databricks.com/aws/en/dev-tools/python-sql-connector"

    @property
    def get_implementation(self) -> DatabricksImplementation:
        return _DATABRICKS_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATABRICKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DATABRICKS,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Databricks",
            caption="Enter your Databricks SQL warehouse credentials to automatically pull your Databricks data into the PostHog Data warehouse. Requires a Unity Catalog catalog.",
            iconPath="/static/services/databricks.png",
            docsUrl="https://posthog.com/docs/cdp/sources/databricks",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["delta lake", "spark", "unity catalog", "sql warehouse"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Server hostname",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="dbc-a1b2345c-d6e7.cloud.databricks.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="http_path",
                        label="HTTP path",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="/sql/1.0/warehouses/abcdef1234567890",
                        secret=False,
                    ),
                    # the validation for these options happens in validate_credentials
                    SourceFieldSelectConfig(
                        name="auth_type",
                        label="Authentication type",
                        required=True,
                        defaultValue="access_token",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Personal access token",
                                value="access_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="access_token",
                                            label="Access token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="dapi...",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Service principal (OAuth)",
                                value="service_principal",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="client_id",
                                            label="Client ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="client_secret",
                                            label="Client secret",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="catalog",
                        label="Catalog",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="main",
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

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` already triggers the credential re-entry gate via `_CONNECTION_TARGET_FIELDS`;
        # declared here too so the intent survives if that framework list ever changes.
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **self.default_non_retryable_errors(),
            "Invalid access token": "Databricks rejected the access token. Check that the personal access token is correct and has not expired or been revoked, then resync.",
            "invalid_client": "Databricks rejected the service principal credentials. Check the client ID and client secret, and that the service principal still exists, then resync.",
            # Unity Catalog error classes are stable identifiers; the object names around them are volatile.
            "CATALOG_NOT_FOUND": "The configured catalog no longer exists in Databricks, or your credentials lost USE CATALOG on it. Check the catalog and grants, then resync.",
            "SCHEMA_NOT_FOUND": "A schema this source syncs no longer exists in Databricks, or your credentials lost USE SCHEMA on it. Check the schema and grants, then resync.",
            "TABLE_OR_VIEW_NOT_FOUND": "A table this source syncs no longer exists in Databricks, or your credentials are no longer authorized to access it. Check that the table still exists and your grants are intact, then resync.",
            "PERMISSION_DENIED": "Your Databricks credentials don't have permission to access this data. Grant USE CATALOG, USE SCHEMA, and SELECT to the connecting principal, then resync.",
            "INSUFFICIENT_PERMISSIONS": "Your Databricks credentials don't have permission to access this data. Grant USE CATALOG, USE SCHEMA, and SELECT to the connecting principal, then resync.",
            # Raised when the SQL warehouse referenced by the HTTP path was deleted.
            "RESOURCE_DOES_NOT_EXIST": "The SQL warehouse referenced by the HTTP path no longer exists. Update the HTTP path to a running SQL warehouse, then resync.",
            # Workspace-level IP ACL rejection — a customer-side network config that retrying can
            # never satisfy. Match the stable phrase, ignoring the appended IP and workspace id.
            "is blocked by Databricks IP ACL for workspace": "PostHog's IP address is blocked by your Databricks workspace's IP access control list. Add PostHog's IP addresses to the workspace's IP ACL, then resync.",
        }

    def validate_credentials(
        self,
        config: DatabricksSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if config.auth_type.selection == "access_token" and not config.auth_type.access_token:
            return False, "Missing required parameter: access token"

        if config.auth_type.selection == "service_principal" and (
            not config.auth_type.client_id or not config.auth_type.client_secret
        ):
            return False, "Missing required parameters: client ID, client secret"

        # Block SSRF to internal hosts before any OAuth/SQL request reaches the pasted host.
        valid_host, host_error = self.is_database_host_valid(clean_databricks_host(config.host), team_id)
        if not valid_host:
            return valid_host, host_error

        try:
            self.get_schemas(config, team_id)
        except Exception as e:
            # The connector raises `databricks.sql.exc.*` subclasses for server/auth errors, but the
            # OAuth M2M path can also raise from the SDK layer — match message fragments across all.
            error_msg = str(e)
            for key, value in DatabricksErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, "Could not connect to Databricks. Please check all connection details are valid."

        return True, None
