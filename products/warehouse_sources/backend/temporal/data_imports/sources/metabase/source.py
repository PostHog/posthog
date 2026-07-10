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

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetabaseSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.metabase import (
    API_KEY_AUTH,
    HOST_NOT_ALLOWED_ERROR,
    SESSION_AUTH,
    MetabaseAuth,
    metabase_source,
    validate_credentials as validate_metabase_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MetabaseSource(SimpleSource[MetabaseSourceConfig]):
    api_docs_url = "https://www.metabase.com/docs/latest/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METABASE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.METABASE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Metabase",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Metabase instance URL and credentials to pull your Metabase data into the PostHog Data warehouse.

Create an API key in your Metabase under **Admin settings > Authentication > API keys** (Metabase v0.47+). Older instances can authenticate with a username and password instead.

The API key (or user) needs read access to the data you want to sync.""",
            iconPath="/static/services/metabase.png",
            docsUrl="https://posthog.com/docs/cdp/sources/metabase",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-company.metabaseapp.com",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue=API_KEY_AUTH,
                        options=[
                            SourceFieldSelectConfigOption(
                                label="API key",
                                value=API_KEY_AUTH,
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="api_key",
                                            label="API key",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="mb_...",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Username & password",
                                value=SESSION_AUTH,
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="username",
                                            label="Username (email)",
                                            type=SourceFieldInputConfigType.EMAIL,
                                            required=False,
                                            placeholder="you@example.com",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="password",
                                            label="Password",
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
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Invalid Metabase credentials": "Your Metabase credentials are invalid or expired. Update them and reconnect.",
            "Invalid Metabase username or password": "Your Metabase username or password is incorrect. Update them and reconnect.",
            "Missing Metabase API key": "No Metabase API key is configured. Update the source configuration and reconnect.",
            "401 Client Error": "Your Metabase credentials are invalid or expired. Update them and reconnect.",
            "403 Client Error": "Your Metabase credentials lack the permissions needed to sync this data. Grant read access and reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The Metabase host is not allowed. Please use your instance's public URL.",
        }

    def _build_auth(self, config: MetabaseSourceConfig) -> MetabaseAuth:
        return MetabaseAuth(
            method=config.auth_method.selection,
            api_key=config.auth_method.api_key,
            username=config.auth_method.username,
            password=config.auth_method.password,
        )

    def get_schemas(
        self,
        config: MetabaseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Metabase exposes no server-side timestamp filter or pagination cursor, so every endpoint
        # is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MetabaseSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_metabase_credentials(config.host, self._build_auth(config), team_id, schema_name)

    def source_for_pipeline(self, config: MetabaseSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return metabase_source(
            host=config.host,
            auth=self._build_auth(config),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            team_id=inputs.team_id,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS
