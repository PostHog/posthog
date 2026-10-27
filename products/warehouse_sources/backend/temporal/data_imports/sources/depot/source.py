import re
import datetime
from typing import ClassVar, Optional, cast

from posthog.dataclasses import frozen

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot import (
    DepotResumeState,
    depot_source,
    validate_credentials as validate_depot_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.depot import DepotSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSchemaSyncType, ExternalDataSourceType

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


_RETRY_LOOKBACK = datetime.timedelta(days=7)
_RECONCILIATION_INTERVAL = datetime.timedelta(days=7)
# GitHub Actions lets a run be re-run for 30 days after it starts. Depot CI documents no limit of its
# own, so this assumes GitHub's.
_RERUN_WINDOW = datetime.timedelta(days=30)
_APPEND_UNSUPPORTED = (
    "Depot CI replays job attempts. Switch this table to incremental merge or full refresh to avoid duplicates."
)


@frozen
class DepotReconciliationCursor:
    cursor_kind: ClassVar[str] = "depot_reconciliation"
    reconciled_at: str
    # The newest run a completed sync scanned. It stands in for the watermark of a table whose runs yield no rows.
    scanned_through: str | None = None


@SourceRegistry.register
class DepotSource(ResumableSource[DepotSourceConfig, DepotResumeState], CursorSource[DepotReconciliationCursor]):
    codebase_detection = detect(
        env=("^DEPOT_",), npm=("@depot/cli", "@depot/sdk-node"), go=("github.com/depot/depot-go",)
    )

    api_docs_url = "https://depot.dev/docs/api/ci/reference"
    lists_tables_without_credentials = True
    history_lookback = datetime.timedelta(days=7)

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEPOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DEPOT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Depot",
            keywords=["depot.dev", "depot ci"],
            caption="Sync Depot CI job attempts, job metrics, artifacts, and failure diagnoses for one GitHub repository. Create an organization API token in your Depot organization settings, then enter the repository as `owner/name`.",
            releaseStatus=ReleaseStatus.BETA,
            docsUrl="https://posthog.com/docs/cdp/sources/depot",
            iconPath="/static/services/depot.png",
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
                        name="repository",
                        label="Repository",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="owner/name",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.depot.canonical_descriptions import (  # noqa: PLC0415 (keeps the descriptions dict off the registry import path)
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            _APPEND_UNSUPPORTED: _APPEND_UNSUPPORTED,
            "401 Client Error": "Depot didn't accept your API token. Create a new organization API token in Depot and reconnect.",
            "403 Client Error": "Your Depot API token can't read Depot CI runs. Use an organization API token and reconnect.",
        }

    def get_schemas(
        self,
        config: DepotSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: DepotSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not _REPOSITORY_RE.match(config.repository):
            return False, "Enter the repository as owner/name, for example PostHog/posthog."
        return validate_depot_credentials(config.api_token, config.repository)

    def cursor_class(self) -> type[DepotReconciliationCursor]:
        return DepotReconciliationCursor

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DepotResumeState]:
        return ResumableSourceManager(inputs, DepotResumeState)

    def source_for_pipeline(
        self,
        config: DepotSourceConfig,
        resumable_source_manager: ResumableSourceManager[DepotResumeState],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.sync_type == ExternalDataSchemaSyncType.APPEND:
            raise ValueError(_APPEND_UNSUPPORTED)
        manager = self.get_cursor_manager(inputs)
        cursor = manager.load()
        now = datetime.datetime.now(datetime.UTC)
        reconciled_at = parse_datetime_value(cursor.reconciled_at) if cursor is not None else None
        watermark = (
            parse_datetime_value(
                inputs.db_incremental_field_last_value or (cursor.scanned_through if cursor is not None else None)
            )
            if inputs.should_use_incremental_field
            else None
        )
        # Creation time cannot reveal a late retry, so each sync replays recent runs and a weekly
        # reconciliation replays older ones. A run re-run after the last reconciliation listed it was
        # created at most _RERUN_WINDOW before that re-run. A sync without a watermark or a past
        # reconciliation reads everything since history_start, the schema's fixed initial floor.
        lower_bound: datetime.datetime | None
        if watermark is None or reconciled_at is None:
            reconcile, lower_bound = True, inputs.history_start
        elif now - reconciled_at >= _RECONCILIATION_INTERVAL:
            reconcile, lower_bound = True, reconciled_at - _RERUN_WINDOW
        else:
            reconcile, lower_bound = False, watermark - _RETRY_LOOKBACK
        if lower_bound is not None and inputs.history_start is not None:
            lower_bound = max(lower_bound, inputs.history_start)

        previous = cursor or DepotReconciliationCursor(reconciled_at=now.isoformat())

        def on_complete(completed_reconciliation: str | None, scanned_through: str | None) -> None:
            manager.stage(
                DepotReconciliationCursor(
                    reconciled_at=completed_reconciliation or previous.reconciled_at,
                    scanned_through=scanned_through or previous.scanned_through,
                )
            )

        return depot_source(
            api_token=config.api_token,
            repository=config.repository,
            created_after=lower_bound,
            reconciled_at=now.isoformat() if reconcile else None,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            endpoint=inputs.schema_name,
            on_complete=on_complete,
        )
