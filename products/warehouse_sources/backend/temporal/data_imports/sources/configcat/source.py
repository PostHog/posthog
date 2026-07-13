from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.configcat import (
    configcat_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.settings import (
    CONFIGCAT_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ConfigCatSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ConfigCatSource(SimpleSource[ConfigCatSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONFIGCAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONFIG_CAT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="ConfigCat",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your ConfigCat Public API credentials to pull your feature-flag account structure into the PostHog Data warehouse.

Create a Public API credential (a username and password pair) under **Public Management API credentials** in your [ConfigCat dashboard](https://app.configcat.com/my-account/public-api-credentials). These are separate from your SDK keys and grant read access to your organizations and products.
""",
            iconPath="/static/services/configcat.png",
            docsUrl="https://posthog.com/docs/cdp/sources/configcat",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="basic_auth_username",
                        label="Public API username",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="basic_auth_password",
                        label="Public API password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.configcat.com": "Your ConfigCat Public API credentials are invalid or have been revoked. Generate a new credential in the ConfigCat dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.configcat.com": "Your ConfigCat Public API credentials do not have access to this data. Check the credential's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: ConfigCatSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — ConfigCat's list endpoints expose no pagination and
        # no server-side timestamp filter, so there is no incremental cursor to advance.
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
        self, config: ConfigCatSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The credential is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.basic_auth_username, config.basic_auth_password)

    def source_for_pipeline(self, config: ConfigCatSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name not in CONFIGCAT_ENDPOINTS:
            raise ValueError(f"Unknown ConfigCat schema '{inputs.schema_name}'")

        return configcat_source(
            username=config.basic_auth_username,
            password=config.basic_auth_password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
