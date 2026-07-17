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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SpaceliftSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RUNS_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.spacelift import (
    SpaceliftResumeConfig,
    spacelift_source,
    validate_credentials as validate_spacelift_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SpaceliftSource(ResumableSource[SpaceliftSourceConfig, SpaceliftResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPACELIFT

    @property
    def connection_host_fields(self) -> list[str]:
        # The account name picks the host the stored API key secret is sent to
        # (https://<account_name>.app.spacelift.io); retargeting it must re-require the secret.
        return ["account_name"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPACELIFT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Spacelift",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Spacelift API key to pull your infrastructure-as-code stacks, runs, policies, and managed resources into the PostHog Data warehouse.

Create an API key under **Organization settings** → **API keys** in your Spacelift account. Grant it at least read access to the spaces you want to sync.

Your account name is the subdomain you use to access Spacelift (e.g. `my-company` for `my-company.app.spacelift.io`).
""",
            iconPath="/static/services/spacelift.png",
            docsUrl="https://posthog.com/docs/cdp/sources/spacelift",
            keywords=["terraform", "opentofu", "iac", "pulumi"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_name",
                        label="Account name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-company",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key_id",
                        label="API key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key_secret",
                        label="API key secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Raised by the apiKeyUser token exchange when the key id/secret is wrong or revoked.
            "Invalid Spacelift API key": "Your Spacelift API key is invalid or has been revoked. Create a new API key in your Spacelift organization settings, then reconnect.",
            # Raised when a query stays unauthorized after a fresh token, i.e. the key lacks space access.
            "Spacelift API returned unauthorized": "Your Spacelift API key does not have access to this data. Grant the key read access to the relevant spaces in Spacelift, then reconnect.",
            "Invalid Spacelift account name": "The Spacelift account name is invalid. Enter only the subdomain of your Spacelift URL (e.g. `my-company` for `my-company.app.spacelift.io`).",
        }

    @staticmethod
    def _description(endpoint: str) -> str | None:
        if endpoint == "runs":
            return (
                "All runs across every stack and module. Incremental syncs re-pull the last "
                f"{RUNS_INCREMENTAL_LOOKBACK_SECONDS // 86400} days so state changes on recent runs are captured"
            )
        if endpoint == "managed_entities":
            return "Terraform/OpenTofu resources managed across your stacks, including drift status"
        return None

    def get_schemas(
        self,
        config: SpaceliftSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                # Incremental runs re-pull a lookback window whose rows only merge
                # dedupes, so append mode would materialize duplicates. The lookback
                # is applied in the transport (the framework-level lookback only
                # shifts datetime cursors, and Spacelift's are epoch-second ints).
                supports_incremental=has_incremental,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=self._description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: SpaceliftSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_spacelift_credentials(config.account_name, config.api_key_id, config.api_key_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SpaceliftResumeConfig]:
        return ResumableSourceManager[SpaceliftResumeConfig](inputs, SpaceliftResumeConfig)

    def source_for_pipeline(
        self,
        config: SpaceliftSourceConfig,
        resumable_source_manager: ResumableSourceManager[SpaceliftResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return spacelift_source(
            account_name=config.account_name,
            api_key_id=config.api_key_id,
            api_key_secret=config.api_key_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
