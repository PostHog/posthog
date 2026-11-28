from typing import Optional, cast

from products.warehouse_sources.sources.hasura._config import HasuraSourceConfig
from products.warehouse_sources.sources.hasura.hasura import (
    ACCESS_DENIED_ERROR,
    INCREMENTAL_FIELD_ERROR,
    NAMESPACE_ERROR,
    NAMING_CONVENTION_ERROR,
    REQUEST_FAILED_ERROR,
    STATEMENT_TIMEOUT_ERROR,
    TABLE_MISSING_ERROR,
    UNORDERED_TABLE_ERROR,
    URL_NOT_ALLOWED_ERROR,
    HasuraClient,
    HasuraConfigError,
    HasuraResumeConfig,
    is_invalid_secret,
    is_refused,
    iter_table_rows,
)
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_incremental_fields,
    detect,
    source_key,
)

SOURCE_KEY = "Hasura"
NAMED_INTROSPECTION_LIMIT = 10

CAPTION = """Connect your Hasura GraphQL Engine (Hasura Cloud or self-hosted v2) to pull the tables and views it exposes into the PostHog Data warehouse.

Enter your GraphQL endpoint, for example `https://my-project.hasura.app/v1/graphql`, and the project's **admin secret** (the `HASURA_GRAPHQL_ADMIN_SECRET` value). On Hasura Cloud, you can find both on the project's **General** settings page.

PostHog reads with the admin role, so it can see every tracked table. Tables with a primary key can sync incrementally on a timestamp, date or integer column. Pick a column that has an index, because each page is ordered by it. Views and tables without a primary key sync with a full refresh.

PostHog reads sources that use the hasura-default naming convention and no root field namespace. It does not list the tables of other sources."""

INVALID_SECRET_MESSAGE = "Hasura rejected the admin secret. Check the secret on your Hasura project, then reconnect."
# Hasura answers a bad secret with HTTP 200, so a 403 comes from a proxy, firewall or IP allowlist.
REFUSED_MESSAGE = (
    "Your Hasura endpoint refused the request. Check that it accepts requests from PostHog, then reconnect."
)


@SourceRegistry.register
class HasuraSource(ResumableSource[HasuraSourceConfig, HasuraResumeConfig]):
    codebase_detection = detect(env=("^HASURA_GRAPHQL_",))

    # GraphQL Engine v2 serves one unversioned API at the fixed /v1/graphql path; the client picks no
    # version, so the framework default applies.
    api_docs_url = "https://hasura.io/docs/2.0/api-reference/graphql-api/overview/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def connection_host_fields(self) -> list[str]:
        # The admin secret is sent to this URL, so changing it must require the secret again.
        return ["graphql_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["graphql"],
            label="Hasura",
            caption=CAPTION,
            releaseStatus=ReleaseStatus.BETA,
            iconPath="/static/warehouse-sources/hasura/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hasura",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="graphql_url",
                        label="GraphQL endpoint",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://my-project.hasura.app/v1/graphql",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="admin_secret",
                        label="Admin secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            ACCESS_DENIED_ERROR: INVALID_SECRET_MESSAGE,
            "401 Client Error": INVALID_SECRET_MESSAGE,
            "403 Client Error": REFUSED_MESSAGE,
            INCREMENTAL_FIELD_ERROR: "This table can no longer sync incrementally on the chosen column. Pick another column or use a full refresh.",
            UNORDERED_TABLE_ERROR: "This table has no primary key and no column to order by, so PostHog can't page through it. Add a primary key in your database, then sync again.",
            NAMING_CONVENTION_ERROR: "Your Hasura source uses the graphql-default naming convention. Switch it to hasura-default to sync it.",
            NAMESPACE_ERROR: "Your Hasura source puts its root fields under a namespace. Remove the namespace in Hasura to sync it.",
            URL_NOT_ALLOWED_ERROR: None,
        }

    def get_retryable_errors(self) -> set[str]:
        # A missing table can come from inconsistent Hasura metadata after a restart, and a statement
        # timeout from load on the database, so both are retried instead of turning the sync off.
        return {TABLE_MISSING_ERROR, STATEMENT_TIMEOUT_ERROR, REQUEST_FAILED_ERROR}

    def get_retry_exhausted_errors(self) -> dict[str, str]:
        return {
            TABLE_MISSING_ERROR: "Hasura doesn't expose this table right now. Check that the table is tracked and that the Hasura metadata is consistent.",
            STATEMENT_TIMEOUT_ERROR: "Your database stopped a query on its statement timeout. Views, tables without a primary key and incremental columns without an index read slower the deeper the sync gets. Add a primary key or an index, or raise the timeout.",
            REQUEST_FAILED_ERROR: "PostHog couldn't reach your Hasura endpoint. Check that it's online and accepts requests from PostHog.",
        }

    def validate_credentials(
        self,
        config: HasuraSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            HasuraClient(config.graphql_url, config.admin_secret).validate()
        except HasuraConfigError as error:
            return False, str(error)
        except Exception as error:
            if is_invalid_secret(error):
                return False, INVALID_SECRET_MESSAGE
            if is_refused(error):
                return False, REFUSED_MESSAGE
            return False, "Could not reach a Hasura GraphQL API at that URL. Check the endpoint, then try again."
        return True, None

    def get_schemas(
        self,
        config: HasuraSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        client = HasuraClient(config.graphql_url, config.admin_secret)
        # A refresh of a few selected tables introspects only those, not every type of the schema.
        if names is not None and len(names) <= NAMED_INTROSPECTION_LIMIT:
            tables = client.get_named_tables(names)
        else:
            tables = client.get_tables()
        schemas = []
        for table in tables.values():
            if names is not None and table.name not in names:
                continue
            incremental_fields = []
            if table.keyset_columns:
                incremental_fields = build_incremental_fields(
                    [
                        (column.name, field_type, column.nullable)
                        for column in table.columns
                        if (field_type := table.incremental_type(column.name)) is not None
                    ]
                )
            schemas.append(
                SourceSchema(
                    name=table.name,
                    supports_incremental=bool(incremental_fields),
                    supports_append=bool(incremental_fields),
                    incremental_fields=incremental_fields,
                    columns=[(column.name, column.scalar, column.nullable) for column in table.columns],
                    detected_primary_keys=list(table.keyset_columns) or None,
                )
            )
        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HasuraResumeConfig]:
        return ResumableSourceManager[HasuraResumeConfig](inputs, HasuraResumeConfig)

    def source_for_pipeline(
        self,
        config: HasuraSourceConfig,
        resumable_source_manager: ResumableSourceManager[HasuraResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        client = HasuraClient(config.graphql_url, config.admin_secret)
        table = client.get_named_tables([inputs.schema_name]).get(inputs.schema_name)
        if table is None:
            raise ValueError(f"{TABLE_MISSING_ERROR} {inputs.schema_name}")

        incremental_field = inputs.incremental_field if inputs.should_use_incremental_field else None
        watermark = inputs.db_incremental_field_last_value if incremental_field else None

        return SourceResponse(
            name=table.name,
            items=lambda: iter_table_rows(client, table, incremental_field, watermark, resumable_source_manager),
            primary_keys=list(table.keyset_columns) or None,
            # An incremental read orders by the incremental column, then the primary key, on the server.
            sort_mode="asc" if incremental_field else None,
        )
