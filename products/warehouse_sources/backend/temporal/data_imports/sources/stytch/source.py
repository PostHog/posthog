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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import StytchSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    STYTCH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.stytch import (
    StytchResumeConfig,
    check_endpoint_access,
    stytch_source,
    validate_credentials as validate_stytch_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StytchSource(ResumableSource[StytchSourceConfig, StytchResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STYTCH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STYTCH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Stytch",
            keywords=["auth", "authentication", "identity"],
            caption="""Enter your Stytch project ID and secret to pull your Stytch users and sessions into the PostHog Data warehouse.

You can find both under [API keys](https://stytch.com/dashboard/api-keys) in your Stytch dashboard. Live credentials (`project-live-...`) sync from `api.stytch.com`; test credentials (`project-test-...`) sync your test environment's data from `test.stytch.com`.

The `organizations` and `members` tables are only available for Stytch B2B projects.""",
            iconPath="/static/services/stytch.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stytch",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="project-live-...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret",
                        label="Secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="secret-live-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Stytch reports credential failures as 400/401 JSON with a stable `error_type`, which the
        # transport surfaces in the raised message. Retrying can never fix these.
        return {
            "error_type=invalid_project_id_authentication": "Your Stytch project ID is invalid. Check it in your Stytch dashboard under API keys, then reconnect.",
            "error_type=invalid_secret_authentication": "Your Stytch secret is invalid or has been revoked. Create a new secret in your Stytch dashboard under API keys, then reconnect.",
            "error_type=unauthorized_credentials": "Your Stytch credentials were rejected. Check your project ID and secret in your Stytch dashboard, then reconnect.",
            "error_type=invalid_authorization_header": "Your Stytch credentials are malformed. Re-enter your project ID and secret, then reconnect.",
        }

    def get_schemas(
        self,
        config: StytchSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Users have no updated-at filter, so incremental only catches new rows; append
                # would still duplicate rows re-pulled after a crash resume, so merge only.
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=STYTCH_ENDPOINTS[endpoint].should_sync_default,
                description=STYTCH_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: StytchSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_stytch_credentials(config.project_id, config.secret):
            return True, None

        return False, "Invalid Stytch project ID or secret"

    def get_endpoint_permissions(
        self, config: StytchSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        # B2C and B2B projects have disjoint API surfaces; probe each requested surface once so
        # the schema picker can flag the tables the connected project can't serve.
        probe_paths = {False: "/v1/users/search", True: "/v1/b2b/organizations/search"}
        surfaces_needed = {
            STYTCH_ENDPOINTS[endpoint].b2b_only for endpoint in endpoints if endpoint in STYTCH_ENDPOINTS
        }
        access_by_surface = {
            b2b: check_endpoint_access(config.project_id, config.secret, probe_paths[b2b]) for b2b in surfaces_needed
        }
        return {
            endpoint: access_by_surface[STYTCH_ENDPOINTS[endpoint].b2b_only] if endpoint in STYTCH_ENDPOINTS else None
            for endpoint in endpoints
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StytchResumeConfig]:
        return ResumableSourceManager[StytchResumeConfig](inputs, StytchResumeConfig)

    def source_for_pipeline(
        self,
        config: StytchSourceConfig,
        resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return stytch_source(
            project_id=config.project_id,
            secret=config.secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
