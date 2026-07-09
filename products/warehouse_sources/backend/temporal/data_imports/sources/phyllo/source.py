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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PhylloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.phyllo import (
    PhylloResumeConfig,
    phyllo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.settings import ENDPOINTS, PHYLLO_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PhylloSource(ResumableSource[PhylloSourceConfig, PhylloResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PHYLLO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PHYLLO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Phyllo",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Phyllo API credentials to pull creator accounts, profiles, content, and income data into the PostHog Data warehouse.

You can find your client ID and secret in the [Phyllo developer dashboard](https://dashboard.getphyllo.com) under **API credentials**. Credentials are environment-specific — sandbox credentials only authenticate against the sandbox environment.
""",
            iconPath="/static/services/phyllo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/phyllo",
            keywords=["creator", "getphyllo"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = "Your Phyllo client ID or secret is invalid for the selected environment. Check the credentials in the Phyllo developer dashboard, then reconnect."
        return {
            "401 Client Error: Unauthorized for url: https://api.getphyllo.com": message,
            "401 Client Error: Unauthorized for url: https://api.sandbox.getphyllo.com": message,
            "403 Client Error: Forbidden for url: https://api.getphyllo.com": message,
            "403 Client Error: Forbidden for url: https://api.sandbox.getphyllo.com": message,
        }

    def get_schemas(
        self,
        config: PhylloSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — see the note in settings.py on the unverified
        # from_date/to_date filters.
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
        self, config: PhylloSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Credentials are environment-wide, so a single probe validates access to every schema.
        return validate_credentials(config.client_id, config.client_secret, config.environment)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PhylloResumeConfig]:
        return ResumableSourceManager[PhylloResumeConfig](inputs, PhylloResumeConfig)

    def source_for_pipeline(
        self,
        config: PhylloSourceConfig,
        resumable_source_manager: ResumableSourceManager[PhylloResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PHYLLO_ENDPOINTS:
            raise ValueError(f"Unknown Phyllo schema '{inputs.schema_name}'")

        return phyllo_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            environment=config.environment,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
