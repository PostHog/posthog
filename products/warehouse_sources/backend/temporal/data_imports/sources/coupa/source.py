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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.coupa import (
    CoupaResumeConfig,
    coupa_source,
    hostname_of,
    validate_credentials as validate_coupa_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoupaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoupaSource(ResumableSource[CoupaSourceConfig, CoupaResumeConfig], ValidateDatabaseHostMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COUPA

    @property
    def connection_host_fields(self) -> list[str]:
        # The instance URL decides where the stored credentials are sent;
        # retargeting it must re-require the secret.
        return ["instance_url"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url": "Coupa rejected the token request. Please check your client ID, client secret, and that the OIDC client has the required scopes.",
            "403 Client Error: Forbidden for url": "Coupa denied access. Please check that the OIDC client has the read scope for this dataset (e.g. core.invoice.read).",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COUPA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Coupa",
            caption="""Connect your Coupa instance to pull your spend management data into the PostHog Data warehouse.

A Coupa admin can create an OIDC client under Setup > Integrations > OAuth2/OpenID Connect Clients with the client credentials grant. Grant it the read scopes for the objects you want to sync (e.g. `core.invoice.read`, `core.purchase_order.read`). The instance URL is your Coupa host, e.g. `https://myorg.coupahost.com`.""",
            iconPath="/static/services/coupa.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coupa",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://myorg.coupahost.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: CoupaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CoupaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.instance_url), team_id)
        except ValueError:
            return False, "Invalid Coupa instance URL"
        if not host_valid:
            return False, host_error

        if validate_coupa_credentials(config.instance_url, config.client_id, config.client_secret):
            return True, None

        return False, "Invalid Coupa credentials. Check the instance URL, client ID, and client secret."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CoupaResumeConfig]:
        return ResumableSourceManager[CoupaResumeConfig](inputs, CoupaResumeConfig)

    def source_for_pipeline(
        self,
        config: CoupaSourceConfig,
        resumable_source_manager: ResumableSourceManager[CoupaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.instance_url), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Coupa host")

        return coupa_source(
            instance_url=config.instance_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
