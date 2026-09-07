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
from products.warehouse_sources.backend.temporal.data_imports.sources.crossref.crossref import (
    CrossrefResumeConfig,
    crossref_source,
    validate_credentials as validate_crossref_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crossref.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crossref import (
    CrossrefSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SCOPE_REQUIRED_MESSAGE = (
    "Set a member ID, funder ID, or journal ISSN before syncing Works. Crossref indexes over "
    "160 million works, so an unscoped sync isn't practical — scope it to a publisher, funder, "
    "or journal first."
)


@SourceRegistry.register
class CrossrefSource(ResumableSource[CrossrefSourceConfig, CrossrefResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://github.com/CrossRef/rest-api-doc"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CROSSREF

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CROSSREF,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Crossref",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Crossref's API is free and public — no API key needed. Add a contact email to get routed to Crossref's faster "polite pool".

The Works table covers Crossref's full DOI registry (160 million+ records), so set a member ID, funder ID, or journal ISSN below to scope which works sync. The Members, Funders, Types, and Licenses tables always sync in full.
""",
            iconPath="/static/services/crossref.png",
            docsUrl="https://posthog.com/docs/cdp/sources/crossref",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="mailto",
                        label="Contact email (optional)",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=False,
                        placeholder="you@example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="member_id",
                        label="Crossref member ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="301",
                        secret=False,
                        caption="Scopes the Works table to one publisher. Look up IDs at [api.crossref.org/members](https://api.crossref.org/members).",
                    ),
                    SourceFieldInputConfig(
                        name="funder_id",
                        label="Funder ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="100000001",
                        secret=False,
                        caption="Scopes the Works table to one funder from the [Open Funder Registry](https://api.crossref.org/funders).",
                    ),
                    SourceFieldInputConfig(
                        name="issn",
                        label="Journal ISSN (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="1932-6203",
                        secret=False,
                        caption="Scopes the Works table to one journal.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.crossref.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "must be a positive integer": "Crossref rejected the member ID or funder ID as invalid. Check the value and try again.",
        }

    def get_schemas(
        self,
        config: CrossrefSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS.keys(),
            INCREMENTAL_FIELDS,
            names,
            # Works rows get re-indexed/re-deposited over time, so append would accumulate one
            # duplicate row per re-fetch of the same DOI; only merge (dedupe on DOI) is offered.
            merge_only={"Works"},
            descriptions={name: cfg.description for name, cfg in ENDPOINTS.items() if cfg.description},
        )

    def _has_scope(self, config: CrossrefSourceConfig) -> bool:
        return bool(config.member_id or config.funder_id or config.issn)

    def validate_credentials(
        self,
        config: CrossrefSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and ENDPOINTS[schema_name].requires_scope and not self._has_scope(config):
            return False, _SCOPE_REQUIRED_MESSAGE

        if validate_crossref_credentials(config.mailto or None):
            return True, None

        return False, "Couldn't reach the Crossref API. Please try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CrossrefResumeConfig]:
        return ResumableSourceManager[CrossrefResumeConfig](inputs, CrossrefResumeConfig)

    def source_for_pipeline(
        self,
        config: CrossrefSourceConfig,
        resumable_source_manager: ResumableSourceManager[CrossrefResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if (
            inputs.schema_name is not None
            and ENDPOINTS[inputs.schema_name].requires_scope
            and not self._has_scope(config)
        ):
            raise ValueError(_SCOPE_REQUIRED_MESSAGE)

        return crossref_source(
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            mailto=config.mailto or None,
            member_id=config.member_id or None,
            funder_id=config.funder_id or None,
            issn=config.issn or None,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
