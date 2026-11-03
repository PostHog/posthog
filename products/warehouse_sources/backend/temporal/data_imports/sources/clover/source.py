from typing import Optional, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.clover import (
    CloverResumeConfig,
    clover_source,
    endpoint_permissions as clover_endpoint_permissions,
    validate_credentials as validate_clover_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.settings import (
    CLOVER_ENDPOINTS,
    DEFAULT_REGION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    AuthConfigBase,
    BearerTokenAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clover import CloverSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_REGION_LABELS = {
    "na": "North America",
    "eu": "Europe",
    "latam": "Latin America",
    "sandbox": "Sandbox",
}


@frozen
class CloverConnection:
    region: str
    merchant_id: str
    auth: AuthConfigBase


@SourceRegistry.register
class CloverSource(ResumableSource[CloverSourceConfig, CloverResumeConfig]):
    codebase_detection = detect(
        script_hosts=("checkout.clover.com",),
        npm=("remote-pay-cloud", "remote-pay-cloud-api"),
        maven=(
            "com.clover.sdk:clover-android-sdk",
            "com.clover.sdk:remote-pay-android-connector",
            "com.clover.sdk:clover-android-connector-sdk",
            "com.clover.sdk:clover-android-loyalty-kit",
            "com.clover.sdk:clover-android-sdk-retrofit",
            "com.clover.sdk:clover-connector-android",
            "com.clover.sdk:clover-connector-java",
        ),
    )

    lists_tables_without_credentials = True

    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.clover.com/dev/reference/api-reference-overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOVER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLOVER,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            keywords=["pos", "point of sale", "fiserv"],
            label="Clover (Fiserv)",
            releaseStatus=ReleaseStatus.BETA,
            caption=(
                "Import data from one Clover merchant. Use a separate source for each merchant. "
                "Enter a merchant API token. "
                "Grant the permissions for the tables you select: Read orders, Read payments, "
                "Read inventory, Read customers, Read employees, and Read merchant. "
                "All tables use full refresh."
            ),
            iconPath="/static/services/clover.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clover",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label=label, value=region)
                            for region, label in _REGION_LABELS.items()
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="merchant_id",
                        label="Merchant ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Clover rejected your credentials. Generate a new API token and update the source.",
            "403 Client Error: Forbidden for url": "Your Clover connection is missing read access for this table. Grant it in the Clover dashboard and sync again.",
            "Missing Clover API token": "The Clover API token is missing. Enter a merchant API token.",
            "Missing Clover merchant ID": "The Clover merchant ID is missing. Copy it from your Clover dashboard.",
            "Clover supports full refresh only": "Change the Clover table sync mode to full refresh.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloverSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            schema.detected_primary_keys = CLOVER_ENDPOINTS[schema.name].primary_keys
        return schemas

    def _connection(self, config: CloverSourceConfig) -> CloverConnection:
        if not config.api_token:
            raise ValueError("Missing Clover API token")
        if not config.merchant_id:
            raise ValueError("Missing Clover merchant ID")
        return CloverConnection(
            region=config.region, merchant_id=config.merchant_id, auth=BearerTokenAuth(config.api_token)
        )

    def validate_credentials(
        self,
        config: CloverSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            connection = self._connection(config)
        except ValueError as e:
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw

        return validate_clover_credentials(
            region=connection.region,
            merchant_id=connection.merchant_id,
            auth=connection.auth,
            schema_name=schema_name,
            api_version=self.resolve_api_version(api_version),
        )

    def get_endpoint_permissions(
        self,
        config: CloverSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        try:
            connection = self._connection(config)
        except ValueError:
            return dict.fromkeys(endpoints)

        return clover_endpoint_permissions(
            region=connection.region,
            merchant_id=connection.merchant_id,
            endpoints=endpoints,
            auth=connection.auth,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CloverResumeConfig]:
        return ResumableSourceManager[CloverResumeConfig](inputs, CloverResumeConfig)

    def source_for_pipeline(
        self,
        config: CloverSourceConfig,
        resumable_source_manager: ResumableSourceManager[CloverResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        connection = self._connection(config)
        return clover_source(
            region=connection.region,
            merchant_id=connection.merchant_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            auth=connection.auth,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
        )
