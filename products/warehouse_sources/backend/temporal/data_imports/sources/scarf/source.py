from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scarf import ScarfSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scarf.scarf import (
    BACKFILL_MESSAGE,
    EXPORT_TOO_LARGE_MESSAGE,
    INVALID_TOKEN_MESSAGE,
    OWNER_MESSAGE,
    PLAN_MESSAGE,
    RUNS_MESSAGE,
    ScarfExportCursor,
    ScarfResumeConfig,
    backfill_is_valid,
    probe_owner,
    scarf_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scarf.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ScarfSource(ResumableSource[ScarfSourceConfig, ScarfResumeConfig], CursorSource[ScarfExportCursor]):
    codebase_detection = detect(
        env=("^SCARF_API_TOKEN$", "^SCARF_ANALYTICS$"),
        npm=("@scarf/scarf",),
        pypi=("scarf-sdk",),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://api-docs.scarf.sh/v2.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCARF

    def cursor_class(self) -> type[ScarfExportCursor]:
        return ScarfExportCursor

    def merge_cursors(self, current: ScarfExportCursor, candidate: ScarfExportCursor) -> ScarfExportCursor:
        # ISO dates order as text, so a run that read less never moves the export day back.
        return max(current, candidate, key=lambda cursor: cursor.next_day)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SCARF,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Scarf",
            keywords=["open source", "package downloads", "oss"],
            caption="""Sync package downloads, pixel views and matched companies from Scarf.

Copy your API token from your [Scarf account settings](https://app.scarf.sh/account). The owner is your Scarf user name or organization name. Event exports need a Scarf Basic or Premium plan, and each day synced uses one export run. A full refresh of an event table exports the whole history window again on every sync, so prefer incremental syncs for those tables.""",
            iconPath="/static/services/scarf.png",
            docsUrl="https://posthog.com/docs/cdp/sources/scarf",
            releaseStatus=ReleaseStatus.BETA,
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
                        name="owner",
                        label="User or organization name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-org",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="backfill_days",
                        label="Days of event history to import first",
                        caption="Defaults to 31. Each day uses one Scarf export run.",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="31",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": INVALID_TOKEN_MESSAGE,
            "402 Client Error": RUNS_MESSAGE,
            "403 Client Error": PLAN_MESSAGE,
            "404 Client Error": OWNER_MESSAGE,
            EXPORT_TOO_LARGE_MESSAGE: EXPORT_TOO_LARGE_MESSAGE,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.scarf.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ScarfSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Today is exported again on the next run, and exports are at-least-once, so only a merge keeps one row per event.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=INCREMENTAL_FIELDS.keys(),
            descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: ScarfSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not backfill_is_valid(config.backfill_days):
            return False, BACKFILL_MESSAGE
        try:
            status = probe_owner(config.api_token, config.owner)
        except ValueError as error:
            return False, str(error)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, INVALID_TOKEN_MESSAGE
        if status == 404:
            return False, OWNER_MESSAGE
        return False, "Couldn't reach Scarf to check the token. Try again in a moment."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ScarfResumeConfig]:
        return ResumableSourceManager[ScarfResumeConfig](inputs, ScarfResumeConfig)

    def source_for_pipeline(
        self,
        config: ScarfSourceConfig,
        resumable_source_manager: ResumableSourceManager[ScarfResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        cursor_manager = self.get_cursor_manager(inputs) if ENDPOINTS[inputs.schema_name].daily else None
        return scarf_source(
            config.api_token, config.owner, config.backfill_days, inputs, resumable_source_manager, cursor_manager
        )
