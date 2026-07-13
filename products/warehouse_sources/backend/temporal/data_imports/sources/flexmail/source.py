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
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.flexmail import (
    FlexmailResumeConfig,
    flexmail_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.settings import (
    ENDPOINTS,
    FLEXMAIL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FlexmailSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FlexmailSource(ResumableSource[FlexmailSourceConfig, FlexmailResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLEXMAIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLEXMAIL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Flexmail",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Flexmail account ID and personal access token to pull your email marketing data into the PostHog Data warehouse.

You can create a personal access token under **Settings → API → Personal access tokens** in [Flexmail](https://app.flexmail.eu). The token grants read access to your contacts, interests, custom fields, preferences, segments, sources, and opt-in forms.
""",
            iconPath="/static/services/flexmail.png",
            docsUrl="https://posthog.com/docs/cdp/sources/flexmail",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.flexmail.eu": "Your Flexmail account ID or personal access token is invalid or has been revoked. Generate a new token under Settings → API → Personal access tokens, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.flexmail.eu": "Your Flexmail personal access token does not have access to this data. Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: FlexmailSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Flexmail's list endpoints expose no server-side
        # timestamp filter, so there is no incremental cursor to advance.
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
        self, config: FlexmailSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Personal access tokens are account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.account_id, config.personal_access_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FlexmailResumeConfig]:
        return ResumableSourceManager[FlexmailResumeConfig](inputs, FlexmailResumeConfig)

    def source_for_pipeline(
        self,
        config: FlexmailSourceConfig,
        resumable_source_manager: ResumableSourceManager[FlexmailResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in FLEXMAIL_ENDPOINTS:
            raise ValueError(f"Unknown Flexmail schema '{inputs.schema_name}'")

        return flexmail_source(
            account_id=config.account_id,
            personal_access_token=config.personal_access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
