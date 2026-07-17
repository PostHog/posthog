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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    WeightsAndBiasesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    WANDB_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.weights_and_biases import (
    WeightsAndBiasesConfigError,
    WeightsAndBiasesResumeConfig,
    validate_credentials as validate_wandb_credentials,
    validate_host as validate_wandb_host,
    weights_and_biases_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WeightsAndBiasesSource(ResumableSource[WeightsAndBiasesSourceConfig, WeightsAndBiasesResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WEIGHTSANDBIASES

    @property
    def connection_host_fields(self) -> list[str]:
        # `entity` selects which W&B account's projects/runs/artifacts the stored key pulls, so
        # changing it retargets the preserved credential at different data. Require the key to be
        # re-entered on change. (`host` — where the key is actually sent — is already handled by
        # the framework's separate `host`-field check.)
        return ["entity"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WEIGHTS_AND_BIASES,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Weights & Biases",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["wandb", "ml", "experiment tracking", "mlops"],
            caption="""Enter your Weights & Biases API key to pull your experiment tracking data into the PostHog Data warehouse.

You can find your API key at [wandb.ai/authorize](https://wandb.ai/authorize). The entity is the username or team whose projects you want to sync.

If you use W&B Dedicated Cloud or a self-managed server, set the host to your deployment's URL (for example `https://acme.wandb.io`). Leave it empty for W&B SaaS cloud.""",
            iconPath="/static/services/weights_and_biases.png",
            docsUrl="https://posthog.com/docs/cdp/sources/weights-and-biases",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="entity",
                        label="Entity (username or team)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-team",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host (Dedicated Cloud or self-managed only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.wandb.ai",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Weights & Biases API key is invalid or has been revoked. Generate a new key at wandb.ai/authorize, then reconnect.",
            "403 Client Error: Forbidden": "Your Weights & Biases API key does not have access to this data. Check the key's permissions on the entity, then reconnect.",
            "Weights & Biases GraphQL error: permission denied": "Your Weights & Biases API key does not have access to this entity or project. Check the entity name and the key's permissions.",
        }

    def get_schemas(
        self,
        config: WeightsAndBiasesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                # Runs mutate after creation (state, summary metrics), so merge is the only
                # safe write mode — append would keep stale duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=WANDB_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: WeightsAndBiasesSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            validate_wandb_host(config.host)
        except WeightsAndBiasesConfigError as err:
            return False, str(err)

        if validate_wandb_credentials(config.api_key, config.host):
            return True, None

        return False, "Invalid Weights & Biases API key"

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[WeightsAndBiasesResumeConfig]:
        return ResumableSourceManager[WeightsAndBiasesResumeConfig](inputs, WeightsAndBiasesResumeConfig)

    def source_for_pipeline(
        self,
        config: WeightsAndBiasesSourceConfig,
        resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return weights_and_biases_source(
            api_key=config.api_key,
            host=config.host,
            entity=config.entity,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
