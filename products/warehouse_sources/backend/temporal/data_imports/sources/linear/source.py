from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.models.integration import OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LinearSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear import (
    LinearResumeConfig,
    linear_source,
    validate_credentials as validate_linear_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LinearSource(ResumableSource[LinearSourceConfig, LinearResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINEAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINEAR,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Linear",
            releaseStatus=ReleaseStatus.GA,
            caption="Connect your Linear workspace to sync issues, projects, teams, and more.",
            iconPath="/static/services/linear.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="linear_integration_id",
                        label="Linear account",
                        required=True,
                        kind="linear",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.linear.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Linear credentials. Please reconnect your account.",
            "403 Client Error": "Access forbidden. Your token may lack required permissions.",
            # The linked OAuth integration was deleted while the source still references it.
            # Retrying can never resolve this — the integration won't reappear — so stop and
            # ask the user to reconnect. Matched as a substring; the trailing integration id varies.
            "Integration not found": "The linked Linear integration no longer exists. Please reconnect your Linear account.",
            # The Linear OAuth app isn't configured on this PostHog instance (missing client id/secret),
            # so the source can't refresh its access token. Deterministic — retrying never resolves it.
            "Linear app not configured": "The Linear app is not configured on this PostHog instance. Please contact support.",
        }

    def _get_access_token(self, config: LinearSourceConfig, team_id: int) -> str:
        integration = self.get_oauth_integration(config.linear_integration_id, team_id)

        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()

        if not integration.access_token:
            raise ValueError("Linear access token not found")
        return integration.access_token

    def get_schemas(
        self,
        config: LinearSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: LinearSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._get_access_token(config, team_id)
            return validate_linear_credentials(access_token)
        except Exception as e:
            return False, str(e)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LinearResumeConfig]:
        return ResumableSourceManager[LinearResumeConfig](inputs, LinearResumeConfig)

    def source_for_pipeline(
        self,
        config: LinearSourceConfig,
        resumable_source_manager: ResumableSourceManager[LinearResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        access_token = self._get_access_token(config, inputs.team_id)

        return linear_source(
            access_token=access_token,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
