import re
from dataclasses import field
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSwitchGroupConfig,
)

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat import (
    BillomatResumeConfig,
    billomat_source,
    validate_credentials as validate_billomat_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billomat import (
    BillomatSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# The Billomat ID is interpolated into https://{billomat_id}.billomat.net, so it must be a bare
# DNS subdomain: alphanumerics and hyphens, starting alphanumeric. This keeps outbound traffic
# pinned to *.billomat.net (a value with a scheme, dot, or path can't build another host).
_BILLOMAT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


@frozen
class _RegisteredAppCredentials:
    app_id: Optional[str]
    app_secret: Optional[str] = field(repr=False)


def _registered_app_credentials(config: BillomatSourceConfig) -> _RegisteredAppCredentials:
    registered_app = config.registered_app
    if registered_app is None or not registered_app.enabled:
        return _RegisteredAppCredentials(app_id=None, app_secret=None)
    return _RegisteredAppCredentials(app_id=registered_app.app_id, app_secret=registered_app.app_secret)


@SourceRegistry.register
class BillomatSource(ResumableSource[BillomatSourceConfig, BillomatResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://www.billomat.com/en/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BILLOMAT

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key/app secret is sent to https://{billomat_id}.billomat.net, so retargeting
        # billomat_id must re-require the secrets (prevents credential exfiltration to another host).
        return ["billomat_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Billomat authentication failed. Check your Billomat ID and API key.",
            "403 Client Error": "Billomat authentication failed. Check your Billomat ID and API key.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BillomatSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BillomatSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not _BILLOMAT_ID_RE.match(config.billomat_id):
            return (
                False,
                "That doesn't look like a Billomat ID. Enter just the subdomain (the 'acme' in "
                "'acme.billomat.net'), not the full URL.",
            )

        registered_app_credentials = _registered_app_credentials(config)
        if validate_billomat_credentials(
            config.api_key, config.billomat_id, registered_app_credentials.app_id, registered_app_credentials.app_secret
        ):
            return True, None

        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BillomatResumeConfig]:
        return ResumableSourceManager[BillomatResumeConfig](inputs, BillomatResumeConfig)

    def source_for_pipeline(
        self,
        config: BillomatSourceConfig,
        resumable_source_manager: ResumableSourceManager[BillomatResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        registered_app_credentials = _registered_app_credentials(config)
        resource = billomat_source(
            api_key=config.api_key,
            billomat_id=config.billomat_id,
            app_id=registered_app_credentials.app_id,
            app_secret=registered_app_credentials.app_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=["id"],
            column_hints=resource.column_hints,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BILLOMAT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Billomat",
            caption="Sync clients, suppliers, invoices, estimates, credit notes and incoming supplier bills from Billomat.",
            docsUrl="https://posthog.com/docs/cdp/sources/billomat",
            iconPath="/static/services/billomat.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["invoicing", "accounting", "invoices"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="billomat_id",
                        label="Billomat ID (subdomain)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                        caption="The subdomain in your Billomat URL, the `acme` in `https://acme.billomat.net`.",
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                        caption="Generate a personal API key under Settings > Administration > Users in Billomat.",
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="registered_app",
                        label="Use a registered app to raise the rate limit?",
                        caption="Optional. Register a free app under Settings > Administration > Apps in Billomat to raise the default limit of 300 requests every 15 minutes.",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="app_id",
                                    label="App ID",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="",
                                    secret=False,
                                ),
                                SourceFieldInputConfig(
                                    name="app_secret",
                                    label="App secret",
                                    type=SourceFieldInputConfigType.PASSWORD,
                                    required=True,
                                    placeholder="",
                                    secret=True,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )
