from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InstagramSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.instagram import (
    INSTAGRAM_AUTH_ERROR_MESSAGE,
    INSTAGRAM_TOKEN_REFRESH_ERROR_MESSAGE,
    InstagramResumeConfig,
    discover_instagram_accounts,
    get_access_token,
    instagram_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.settings import INSTAGRAM_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InstagramSource(ResumableSource[InstagramSourceConfig, InstagramResumeConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INSTAGRAM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            INSTAGRAM_TOKEN_REFRESH_ERROR_MESSAGE: None,
            INSTAGRAM_AUTH_ERROR_MESSAGE: INSTAGRAM_AUTH_ERROR_MESSAGE,
            "No Instagram professional account is linked": (
                "No Instagram professional account is linked to the connected Facebook account. "
                "Link an Instagram professional account to a Facebook Page and re-authorize."
            ),
        }

    def get_schemas(
        self,
        config: InstagramSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=bool(endpoint["incremental_fields"]),
                supports_append=bool(endpoint["incremental_fields"]),
                incremental_fields=endpoint["incremental_fields"],
                description=endpoint["description"],
                should_sync_default=endpoint["should_sync_default"],
            )
            for name, endpoint in INSTAGRAM_ENDPOINTS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InstagramResumeConfig]:
        return ResumableSourceManager[InstagramResumeConfig](inputs, InstagramResumeConfig)

    def source_for_pipeline(
        self,
        config: InstagramSourceConfig,
        resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return instagram_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    def validate_credentials(
        self,
        config: InstagramSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        try:
            access_token = get_access_token(config.instagram_integration_id, team_id)
        except Exception as e:
            return False, f"Could not load Instagram credentials: {e}"

        try:
            accounts = discover_instagram_accounts(access_token)
        except Exception as e:
            return False, f"Failed to list Instagram accounts: {e}"

        if not accounts:
            return (
                False,
                "No Instagram professional account is linked to the connected Facebook account. "
                "Link an Instagram Business or Creator account to a Facebook Page the connected "
                "user manages, then reconnect.",
            )

        return True, None

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INSTAGRAM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Instagram",
            caption=(
                "Connect a Facebook account that manages one or more Instagram professional "
                "(Business or Creator) accounts to sync profiles, posts, stories, and daily "
                "account insights. All linked Instagram accounts are synced.\n\n"
                "Personal Instagram accounts are not supported by Meta's API — the Instagram "
                "account must be linked to a Facebook Page."
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-instagram",
            iconPath="/static/services/instagram.png",
            docsUrl="https://posthog.com/docs/cdp/sources/instagram",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="instagram_integration_id",
                        label="Instagram account",
                        required=True,
                        kind="instagram",
                        requiredScopes="instagram_basic,instagram_manage_insights,pages_show_list,pages_read_engagement",
                    ),
                ],
            ),
        )
