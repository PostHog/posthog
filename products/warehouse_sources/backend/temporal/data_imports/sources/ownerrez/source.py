from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ownerrez import (
    OwnerrezSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.ownerrez import (
    OwnerRezResumeConfig,
    ownerrez_source,
    validate_credentials as validate_ownerrez_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OwnerrezSource(ResumableSource[OwnerrezSourceConfig, OwnerRezResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # OwnerRez's API is unversioned in practice: paths are pinned under /v2 with no dated
    # version header, param, or named release to declare.
    api_docs_url = "https://api.ownerreservations.com/help/v2"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OWNERREZ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OWNERREZ,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="OwnerRez",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your OwnerRez account email and personal access token to pull your bookings, guests, payments, and property data into the PostHog Data warehouse.

Create a personal access token under **Settings → Advanced Tools → Developer/API Settings** in your OwnerRez account. OwnerRez rate limits personal access tokens per IP address to two accounts every 24 hours, so this connection method suits a single OwnerRez account rather than many.""",
            iconPath="/static/services/ownerrez.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ownerrez",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="email",
                        label="Account email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pt_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your OwnerRez credentials are invalid. Check your account email and personal access token, then reconnect.",
            "403 Client Error: Forbidden": "Your OwnerRez account does not have permission to access this data. Check your account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: OwnerrezSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OwnerrezSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_ownerrez_credentials(config.email, config.api_key)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid OwnerRez account email or personal access token"
        return False, "Could not connect to OwnerRez with the provided account email and personal access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OwnerRezResumeConfig]:
        return ResumableSourceManager[OwnerRezResumeConfig](inputs, OwnerRezResumeConfig)

    def source_for_pipeline(
        self,
        config: OwnerrezSourceConfig,
        resumable_source_manager: ResumableSourceManager[OwnerRezResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ownerrez_source(
            email=config.email,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
