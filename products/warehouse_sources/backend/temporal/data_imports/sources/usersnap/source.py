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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UsersnapSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap import (
    UsersnapResumeConfig,
    usersnap_source,
    validate_credentials as validate_usersnap_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UsersnapSource(ResumableSource[UsersnapSourceConfig, UsersnapResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USERSNAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.USERSNAP,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Usersnap",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Usersnap REST API credentials to pull your Usersnap projects and feedback items into the PostHog Data warehouse.

The Usersnap REST API is a gated feature: it must be enabled on your plan by Usersnap (contact their customer success team). Once enabled, generate a JWT secret under **Settings → REST API** in Usersnap and copy both the secret and its JWT ID here — PostHog signs the short-lived bearer tokens for you.""",
            iconPath="/static/services/usersnap.png",
            docsUrl="https://posthog.com/docs/cdp/sources/usersnap",
            keywords=["feedback", "bug reporting"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="jwt_secret",
                        label="JWT secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="jwt_id",
                        label="JWT ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://platform.usersnap.com": "Usersnap authentication failed. Check that the JWT secret and JWT ID match a secret generated under Settings → REST API in Usersnap, then reconnect.",
            "403 Client Error: Forbidden for url: https://platform.usersnap.com": "Usersnap denied access. The REST API is a gated feature — make sure it is enabled on your Usersnap plan.",
        }

    def get_schemas(
        self,
        config: UsersnapSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "feedbacks":
                return (
                    "Feedback items across all projects. Incremental syncs pick up newly created "
                    "feedback; changes to existing items (status, assignee) are only reflected on a full refresh"
                )
            if endpoint == "project_assignees":
                return "Maps which users are available as assignees on each project"
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                # The incremental filter uses gte, which re-pulls the watermark row; only merge
                # dedupes it on the primary key, append would materialize it as a duplicate.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: UsersnapSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_usersnap_credentials(config.jwt_secret, config.jwt_id):
            return True, None

        return (
            False,
            "Invalid Usersnap credentials. Check your JWT secret and JWT ID, and that the REST API is enabled on your Usersnap plan.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UsersnapResumeConfig]:
        return ResumableSourceManager[UsersnapResumeConfig](inputs, UsersnapResumeConfig)

    def source_for_pipeline(
        self,
        config: UsersnapSourceConfig,
        resumable_source_manager: ResumableSourceManager[UsersnapResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return usersnap_source(
            jwt_secret=config.jwt_secret,
            jwt_id=config.jwt_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
