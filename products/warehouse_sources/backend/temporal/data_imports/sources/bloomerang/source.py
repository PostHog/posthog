from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.bloomerang import (
    BloomerangResumeConfig,
    bloomerang_source,
    validate_credentials as validate_bloomerang_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    UNVERSIONED_API_VERSION,
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bloomerang import (
    BloomerangSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BloomerangSource(ResumableSource[BloomerangSourceConfig, BloomerangResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # The source has always spoken Bloomerang's current v2 REST API on the wire (BASE_URL ends in
    # `/v2`); the framework label was just the unversioned default. Bloomerang has now deprecated
    # its v1 REST API, so `v2` is declared as the explicit default and the legacy unversioned `v1`
    # label is marked deprecated. There is no per-version dispatch — `/v2` is a fixed path segment,
    # not a request input — so both labels resolve to identical requests. Existing `v1`-pinned rows
    # keep working unchanged and are repinned to `v2` by data migration (a pure relabel, not a move).
    # No calendar sunset date is published for v1.
    supported_versions = (UNVERSIONED_API_VERSION, "v2")
    default_version = "v2"
    deprecated_versions = (VersionDeprecation(version=UNVERSIONED_API_VERSION, sunset_at=None),)
    api_docs_url = "https://bloomerang.com/api/rest-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLOOMERANG

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Bloomerang API key is invalid or has been revoked. Generate a new private key under User Settings, then reconnect.",
            "403 Client Error": "Your Bloomerang API key does not have permission to read this data. Check the key's permissions, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BloomerangSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BloomerangSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_bloomerang_credentials(config.api_key)
        if is_valid:
            return True, None
        if status_code == 401:
            return False, "Invalid Bloomerang API key"
        return False, "Could not connect to Bloomerang with the provided API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BloomerangResumeConfig]:
        return ResumableSourceManager[BloomerangResumeConfig](inputs, BloomerangResumeConfig)

    def source_for_pipeline(
        self,
        config: BloomerangSourceConfig,
        resumable_source_manager: ResumableSourceManager[BloomerangResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bloomerang_source(
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

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BLOOMERANG,
            category=DataWarehouseSourceCategory.CRM,
            keywords=["donor", "nonprofit", "fundraising"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Bloomerang private API key to pull your donor database into the PostHog Data warehouse, including constituents, transactions, interactions, appeals, campaigns, and funds.

Generate a private API key under **Settings → User Settings → API Keys** in your Bloomerang account. This key grants full read/write access to your Bloomerang data, so keep it secret.""",
            iconPath="/static/services/bloomerang.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bloomerang",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
