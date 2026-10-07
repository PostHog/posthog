from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.proofpointtap import (
    ProofpointTapSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.proofpoint_tap import (
    TapCursor,
    TapResumeState,
    parse_timestamp,
    proofpoint_tap_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.settings import (
    API_DOCS_URL,
    API_VERSION,
    AUTH_ERRORS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ProofpointTapSource(ResumableSource[ProofpointTapSourceConfig, TapResumeState], CursorSource[TapCursor]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PROOFPOINTTAP

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERRORS[401],
            "403 Client Error": AUTH_ERRORS[403],
            "Service Id / Credentials authentication failed": AUTH_ERRORS[401],
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def cursor_class(self) -> type[TapCursor]:
        return TapCursor

    def merge_cursors(self, current: TapCursor, candidate: TapCursor) -> TapCursor:
        return max((current, candidate), key=lambda cursor: parse_timestamp(cursor.query_end_time))

    def get_schemas(
        self,
        config: ProofpointTapSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: ProofpointTapSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TapResumeState]:
        return ResumableSourceManager(inputs, TapResumeState)

    def source_for_pipeline(
        self,
        config: ProofpointTapSourceConfig,
        resumable_source_manager: ResumableSourceManager[TapResumeState],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return proofpoint_tap_source(
            config,
            inputs,
            resumable_source_manager,
            self.get_cursor_manager(inputs),
            self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PROOFPOINTTAP,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Proofpoint TAP",
            caption="Create a service principal and secret in the TAP dashboard under Settings > Connected Applications. "
            "A TAP subscription is required. The API retains seven days of events. Sync at least once each day.",
            docsUrl=API_DOCS_URL,
            iconPath="/static/services/proofpoint_tap.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="service_principal",
                        label="Service principal",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret",
                        label="Secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
