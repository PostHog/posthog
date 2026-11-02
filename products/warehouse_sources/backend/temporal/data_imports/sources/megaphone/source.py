from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.megaphone import (
    MegaphoneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.megaphone.megaphone import (
    MegaphoneResumeConfig,
    is_valid_organization_id,
    megaphone_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.megaphone.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MegaphoneSource(ResumableSource[MegaphoneSourceConfig, MegaphoneResumeConfig]):
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developers.megaphone.fm/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEGAPHONE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEGAPHONE,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Megaphone",
            caption="""Sync your Megaphone networks, podcasts and episodes into PostHog. Download and impression metrics are not available through the Megaphone API.

Create an API token in Megaphone under **Settings > Generate new token**. The organization ID is in the address bar after `/organizations/` when you are signed in.""",
            iconPath="/static/services/megaphone.png",
            docsUrl="https://posthog.com/docs/cdp/sources/megaphone",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["podcast"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="3ea516ea-a2d1-11e6-8e62-83147939747c",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.megaphone.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Megaphone rejected the API token. Create a new token in Megaphone, then reconnect the source.",
            "403 Client Error: Forbidden for url": "The Megaphone API token can't read this organization. Check the organization ID and the token's user role, then reconnect the source.",
            "Invalid Megaphone organization ID": "The organization ID is not valid. Copy it from the Megaphone address bar, then reconnect the source.",
        }

    def get_schemas(
        self,
        config: MegaphoneSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MegaphoneSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        organization_id = config.organization_id.strip()
        if not is_valid_organization_id(organization_id):
            return (
                False,
                "That doesn't look like a Megaphone organization ID. Copy the ID from the Megaphone address bar.",
            )
        is_valid, status = probe_credentials(config.api_token, organization_id)
        if is_valid:
            return True, None
        if status == 401:
            return False, "Megaphone rejected the API token. Check that you pasted the whole token."
        if status in (403, 404):
            return False, "The API token can't read this organization. Check the organization ID."
        return (
            False,
            "Couldn't reach Megaphone with these credentials. Check the token and organization ID, then try again.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MegaphoneResumeConfig]:
        return ResumableSourceManager[MegaphoneResumeConfig](inputs, MegaphoneResumeConfig)

    def source_for_pipeline(
        self,
        config: MegaphoneSourceConfig,
        resumable_source_manager: ResumableSourceManager[MegaphoneResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return megaphone_source(
            api_token=config.api_token,
            organization_id=config.organization_id.strip(),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
