from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IntercomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.intercom import (
    intercom_source,
    validate_credentials as validate_intercom_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.settings import (
    INCREMENTAL_FIELDS,
    INTERCOM_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IntercomSource(SimpleSource[IntercomSourceConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INTERCOM

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Intercom connection is invalid or expired. Please reconnect it.",
            "403 Client Error": "Your Intercom connection is missing required scopes. Please update permissions and reconnect.",
            # Deterministic credential/config errors from OAuthMixin and source_for_pipeline. The
            # integration row is gone or unconfigured, so retrying can never succeed — the customer
            # must reconnect. Match on the stable prefix so the volatile integration ID is ignored.
            "Missing integration ID": "Intercom integration ID is not configured. Please reconnect your Intercom account.",
            "Integration not found": "The linked Intercom integration no longer exists. Please reconnect your Intercom account.",
            "Intercom access token not found": "Intercom OAuth access token is missing. Please reconnect your Intercom account.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INTERCOM,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            caption="Select an existing Intercom workspace to link to PostHog or create a new connection",
            iconPath="/static/services/intercom.png",
            docsUrl="https://posthog.com/docs/cdp/sources/intercom",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="intercom_integration_id",
                        label="Intercom workspace",
                        required=True,
                        kind="intercom",
                    ),
                ],
            ),
            featureFlag="dwh_intercom",
            releaseStatus=ReleaseStatus.BETA,
        )

    def get_schemas(
        self,
        config: IntercomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = []
        for endpoint_config in INTERCOM_ENDPOINTS.values():
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint_config.name, [])
            supports_incremental = bool(incremental_fields)
            schemas.append(
                SourceSchema(
                    name=endpoint_config.name,
                    supports_incremental=supports_incremental,
                    supports_append=supports_incremental,
                    incremental_fields=incremental_fields,
                )
            )
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: IntercomSourceConfig, team_id: int, schema_name: str | None = None
    ) -> tuple[bool, str | None]:
        try:
            integration = self.get_oauth_integration(config.intercom_integration_id, team_id)
        except ValueError as e:
            return False, str(e)

        if not integration.access_token:
            return False, "Intercom integration has no access token. Please reconnect."

        return validate_intercom_credentials(integration.access_token, schema_name=schema_name)

    def source_for_pipeline(self, config: IntercomSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.intercom_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Intercom access token not found for job {inputs.job_id}")

        return intercom_source(
            access_token=integration.access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
