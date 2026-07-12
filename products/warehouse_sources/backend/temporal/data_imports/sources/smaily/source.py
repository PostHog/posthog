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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SmailySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.settings import ENDPOINTS, SMAILY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.smaily import (
    SmailyResumeConfig,
    smaily_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SmailySource(ResumableSource[SmailySourceConfig, SmailyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMAILY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SMAILY,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Smaily",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["sendsmaily", "email marketing"],
            caption="""Enter your Smaily API credentials to pull your email marketing data into the PostHog Data warehouse.

Create an API user in [Smaily](https://smaily.com) under **Account preferences → Integrations → API users**. Your subdomain is the first part of your Smaily URL, e.g. `mycompany` for `mycompany.sendsmaily.net`.
""",
            iconPath="/static/services/smaily.png",
            docsUrl="https://posthog.com/docs/cdp/sources/smaily",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Smaily subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mycompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="API username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="API password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API password is sent to `{subdomain}.sendsmaily.net`; retargeting the
        # subdomain must re-require the credentials.
        return ["subdomain"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Smaily authentication failed. Check your subdomain, API username and password, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Smaily API user does not have access to this data. Check the API user's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: SmailySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Smaily's list endpoints expose no server-side
        # timestamp filter, so there is no incremental cursor to advance.
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
        self, config: SmailySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API user is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.subdomain, config.username, config.password)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SmailyResumeConfig]:
        return ResumableSourceManager[SmailyResumeConfig](inputs, SmailyResumeConfig)

    def source_for_pipeline(
        self,
        config: SmailySourceConfig,
        resumable_source_manager: ResumableSourceManager[SmailyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SMAILY_ENDPOINTS:
            raise ValueError(f"Unknown Smaily schema '{inputs.schema_name}'")

        return smaily_source(
            subdomain=config.subdomain,
            username=config.username,
            password=config.password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
