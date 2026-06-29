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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MuxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.mux import (
    DEFAULT_VALIDATION_PATH,
    MuxResumeConfig,
    get_validation_status,
    mux_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MUX_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MuxSource(ResumableSource[MuxSourceConfig, MuxResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MUX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MUX,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Mux",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Mux Access Token ID and Secret Key to pull your Mux Video data into the PostHog Data warehouse.

Create an access token under [Settings → Access Tokens](https://dashboard.mux.com/settings/access-tokens) in your Mux dashboard. Tokens are scoped to a single Mux environment.

Grant the following read permissions:
- **Mux Video** (read) — required for assets, live streams, uploads, playback restrictions and transcription vocabularies
- **Mux System** (read) — required for signing keys
""",
            iconPath="/static/services/mux.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mux",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token_id",
                        label="Access Token ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret Key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mux.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/revoked token surfaces as a 401 when `_fetch_page` calls `raise_for_status()`;
            # a token missing the required read scope surfaces as a 403 at sync time. Neither can be
            # fixed by retrying. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.mux.com": "Your Mux access token is invalid or has been revoked. Create a new access token in your Mux dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.mux.com": "Your Mux access token is missing the read permissions needed to sync this data. Grant Mux Video and Mux System read access, then reconnect.",
        }

    def get_schemas(
        self,
        config: MuxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Mux exposes no server-side timestamp filter on its list endpoints, so every stream is
        # full refresh only — no incremental/append support.
        def _build_schema(endpoint: str) -> SourceSchema:
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=MUX_ENDPOINTS[endpoint].should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MuxSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        path = MUX_ENDPOINTS[schema_name].path if schema_name in MUX_ENDPOINTS else DEFAULT_VALIDATION_PATH
        status = get_validation_status(config.access_token_id, config.secret_key, path)

        if status == 200:
            return True, None

        # 401 means the token itself is bad. A 403 means the token is genuine but lacks the scope for
        # this endpoint — accept it at source-create (schema_name is None) since users may only grant
        # scopes for the streams they want; re-raise it only when validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None

        if status == 403:
            return False, "Your Mux access token does not have permission to read this data."

        return False, "Invalid Mux access token. Check the Access Token ID and Secret Key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MuxResumeConfig]:
        return ResumableSourceManager[MuxResumeConfig](inputs, MuxResumeConfig)

    def source_for_pipeline(
        self,
        config: MuxSourceConfig,
        resumable_source_manager: ResumableSourceManager[MuxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mux_source(
            access_token_id=config.access_token_id,
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
