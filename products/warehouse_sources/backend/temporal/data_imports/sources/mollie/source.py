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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MollieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie import (
    MollieResumeConfig,
    mollie_source,
    validate_credentials as validate_mollie_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MollieSource(ResumableSource[MollieSourceConfig, MollieResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOLLIE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.mollie.com": "Mollie authentication failed. Please check your API key.",
            "403 Client Error: Forbidden for url: https://api.mollie.com": "Mollie denied access. Please check that your API key has access to this data.",
            # Mollie rejects profile-scoped list endpoints with a 400 when the credential is an
            # organization/OAuth access token, which needs an explicit profile a regular API key
            # supplies implicitly. The request shape is fixed, so retrying replays the same failure.
            # The match is any Mollie 400, so the message leads with the common cause but hedges.
            "400 Client Error: Bad Request for url: https://api.mollie.com": "Mollie rejected the request as a Bad Request (400). The most common cause is connecting an organization or OAuth access token, which needs a specific profile that a regular API key supplies implicitly — reconnect with a regular Mollie API key (starts with `live_` or `test_`). If you are already using a regular API key, contact support so we can investigate.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MOLLIE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Mollie",
            caption="""Enter your Mollie API key to pull your Mollie payments data into the PostHog Data warehouse.

You can find your API key in the [Mollie dashboard](https://my.mollie.com/dashboard/developers/api-keys) under Developers > API keys. Use a live key (`live_...`) for production data — test keys only return test-mode data.""",
            iconPath="/static/services/mollie.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mollie",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="live_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MollieSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # No Mollie list endpoint exposes a server-side date filter, and mutable
        # objects change status after creation, so every stream is full refresh.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: MollieSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_mollie_credentials(config.api_key):
            return True, None

        return False, "Invalid Mollie API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MollieResumeConfig]:
        return ResumableSourceManager[MollieResumeConfig](inputs, MollieResumeConfig)

    def source_for_pipeline(
        self,
        config: MollieSourceConfig,
        resumable_source_manager: ResumableSourceManager[MollieResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mollie_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
