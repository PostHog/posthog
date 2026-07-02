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
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.culture_amp import (
    CultureAmpResumeConfig,
    culture_amp_source,
    validate_credentials as validate_culture_amp_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CultureAmpSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CultureAmpSource(ResumableSource[CultureAmpSourceConfig, CultureAmpResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CULTUREAMP

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://api.cultureamp.com/v1/oauth2/token": "Culture Amp rejected the token request. Please check your client ID, client secret, and account ID, and that the credentials have the required permissions.",
            "401 Client Error: Unauthorized for url: https://api.cultureamp.com/v1/oauth2/token": "Culture Amp authentication failed. Please check your client ID and client secret.",
            "403 Client Error: Forbidden for url: https://api.cultureamp.com": "Culture Amp denied access. Please check that your API credentials have the required permissions for this dataset.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CULTURE_AMP,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Culture Amp",
            caption="""Connect your Culture Amp account to pull your employee experience data into the PostHog Data warehouse.

An account admin can generate API credentials in Culture Amp under Settings > Integrations > Culture Amp API. Grant the employees, employee demographics, and performance evaluations read permissions. The account ID is the entity ID shown alongside your credentials.""",
            iconPath="/static/services/culture_amp.png",
            docsUrl="https://posthog.com/docs/cdp/sources/culture-amp",
            releaseStatus=ReleaseStatus.ALPHA,
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
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="8ed17dce-9eca-4383-a9e1-54f82c362b6d",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CultureAmpSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CultureAmpSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_culture_amp_credentials(config.client_id, config.client_secret, config.account_id):
            return True, None

        return (
            False,
            "Invalid Culture Amp credentials. Check the client ID, client secret, and account ID, and that the credentials have the employees read permission.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CultureAmpResumeConfig]:
        return ResumableSourceManager[CultureAmpResumeConfig](inputs, CultureAmpResumeConfig)

    def source_for_pipeline(
        self,
        config: CultureAmpSourceConfig,
        resumable_source_manager: ResumableSourceManager[CultureAmpResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return culture_amp_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
