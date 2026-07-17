from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VeracodeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    VERACODE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.veracode import (
    VeracodeResumeConfig,
    validate_credentials as validate_veracode_credentials,
    veracode_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VeracodeSource(ResumableSource[VeracodeSourceConfig, VeracodeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VERACODE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VERACODE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Veracode",
            caption=(
                "Connect Veracode with an API service account's **API ID** and **secret key**, generated under "
                "**Account settings → API credentials** in the Veracode Platform. Requests are signed with "
                "Veracode's HMAC scheme.\n\n"
                "The service account needs the **Results API** and **Applications API** roles to read the "
                "application portfolio and findings. Pick the region your Veracode account lives in — data is "
                "isolated per region."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/veracode",
            iconPath="/static/services/veracode.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_id",
                        label="API ID",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="com",
                        options=[
                            SourceFieldSelectConfigOption(label="US commercial (api.veracode.com)", value="com"),
                            SourceFieldSelectConfigOption(label="European (api.veracode.eu)", value="eu"),
                            SourceFieldSelectConfigOption(label="US federal (api.veracode.us)", value="us"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "Veracode rejected the credentials. Generate a fresh API ID and secret key for the service "
                "account in the Veracode Platform (Account settings → API credentials) and reconnect."
            ),
            "403 Client Error: Forbidden": (
                "The Veracode service account is missing the roles needed to sync this data. Grant the Results "
                "API and Applications API roles to the account, then reconnect."
            ),
        }

    def get_schemas(
        self,
        config: VeracodeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(name)),
                supports_append=bool(INCREMENTAL_FIELDS.get(name)),
                incremental_fields=INCREMENTAL_FIELDS.get(name, []),
                should_sync_default=endpoint.should_sync_default,
            )
            for name, endpoint in VERACODE_ENDPOINTS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: VeracodeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_veracode_credentials(config.api_id, config.api_secret, config.region)
        if ok:
            return True, None

        # A 403 means the token is genuine but the service account lacks a role. Accept it at
        # source-create (the user may only have granted roles for the tables they want) and only
        # surface it when validating a specific schema.
        if status_code == 403 and schema_name is None:
            return True, None

        if status_code in (401, 403):
            return False, "Veracode rejected the credentials. Check the API ID, secret key, region, and account roles."

        return False, "Could not reach Veracode with the provided credentials."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VeracodeResumeConfig]:
        return ResumableSourceManager[VeracodeResumeConfig](inputs, VeracodeResumeConfig)

    def source_for_pipeline(
        self,
        config: VeracodeSourceConfig,
        resumable_source_manager: ResumableSourceManager[VeracodeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Veracode endpoint: {inputs.schema_name}")

        return veracode_source(
            api_id=config.api_id,
            api_secret=config.api_secret,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
