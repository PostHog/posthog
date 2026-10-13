import re
import datetime
from typing import ClassVar, Optional, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot import (
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
_APPEND_UNSUPPORTED = (
    "Depot CI replays job attempts. Switch this table to incremental merge or full refresh to avoid duplicates."
)


@frozen
class DepotReconciliationCursor:
    cursor_kind: ClassVar[str] = "depot_reconciliation"
    reconciled_at: str


@SourceRegistry.register
class DepotSource(SimpleSource[DepotSourceConfig], CursorSource[DepotReconciliationCursor]):
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
            caption="Sync Depot CI job attempts for one GitHub repository. Create an organization API token in your Depot organization settings, then enter the repository as `owner/name`.",
            releaseStatus=ReleaseStatus.ALPHA,
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

    def source_for_pipeline(self, config: DepotSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.sync_type == ExternalDataSchemaSyncType.APPEND:
            raise ValueError(_APPEND_UNSUPPORTED)
        manager = self.get_cursor_manager(inputs)
        cursor = manager.load()
        now = datetime.datetime.now(datetime.UTC)
        reconciled_at = parse_datetime_value(cursor.reconciled_at) if cursor is not None else None
        watermark = (
            parse_datetime_value(inputs.db_incremental_field_last_value)
            if inputs.should_use_incremental_field
            else None
        )
        reconcile = reconciled_at is None or now - reconciled_at >= _RECONCILIATION_INTERVAL or watermark is None
        # Creation time cannot reveal a late retry. Replay recent runs each sync and retained history
        # weekly; history_start is the schema's fixed initial floor, not a rolling seven-day window.
        lower_bound = inputs.history_start
        if not reconcile and watermark is not None:
            lower_bound = watermark - _RETRY_LOOKBACK
            if inputs.history_start is not None:
                lower_bound = max(lower_bound, inputs.history_start)

        return depot_source(
            api_token=config.api_token,
            repository=config.repository,
            created_after=lower_bound,
            logger=inputs.logger,
            on_complete=(lambda: manager.stage(DepotReconciliationCursor(reconciled_at=now.isoformat())))
            if reconcile
            else None,
        )
