from typing import Optional, cast

import requests

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.adjust import (
    AdjustCredentialsError,
    AdjustResumeConfig,
    AdjustRetryableError,
    adjust_source,
    validate_credentials as validate_adjust_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.settings import (
    DESCRIPTIONS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adjust import AdjustSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AdjustSource(ResumableSource[AdjustSourceConfig, AdjustResumeConfig]):
    # The Report Service API carries no version token in its path, headers, or params, so there is
    # no vendor version to pin.
    api_docs_url = "https://dev.adjust.com/en/api/rs-api/"

    lists_tables_without_credentials = True  # static report catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADJUST

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://automate.adjust.com": "Adjust rejected your API token. Generate a new token in the Adjust dashboard and reconnect.",
            "403 Client Error: Forbidden for url: https://automate.adjust.com": "Adjust denied access. Check that your user has reporting access to these apps and that your account includes the Report Service API.",
            # A 400 means the report request itself is invalid (unknown dimension or metric, or an
            # app token that isn't in this account). The request shape is fixed per table, so
            # retrying it identically can never succeed.
            "400 Client Error: Bad Request for url: https://automate.adjust.com": "Adjust rejected the report request. Check that the app tokens belong to this account and that your account has access to the requested metrics.",
            "404 Client Error: Not Found for url: https://automate.adjust.com": "Adjust could not find the requested report data. Check the app tokens on this source.",
        }

    def get_retryable_errors(self) -> set[str]:
        # The tracked session's own urllib3 retries (see common/http/transport.py) cover read
        # timeouts and connection failures on GET, not just 429/5xx. Once that budget exhausts,
        # requests wraps the failure as this host-scoped pool error and Temporal retries the
        # whole activity from there, so it's transient and self-recovering rather than a bug.
        return {"HTTPSConnectionPool(host='automate.adjust.com', port=443)"}

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ADJUST,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Adjust",
            caption="""Enter your Adjust API token to pull aggregated attribution and performance reports into the PostHog Data warehouse.

Find your API token in the Adjust dashboard under your account menu > Account settings. The token needs reporting access to the apps you want to import. Leave app tokens blank to import every app the token can read, or enter a comma-separated list to narrow it down.

Adjust's Report Service API returns metrics aggregated per day, so these tables are daily time series rather than user-level events. Raw user-level data needs server callbacks or a cloud storage upload, which can't be set up through the API.""",
            iconPath="/static/services/adjust.png",
            docsUrl="https://posthog.com/docs/cdp/sources/adjust",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["mobile attribution", "mmp"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="app_tokens",
                        label="App tokens (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="abc123def456,ghi789jkl012",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AdjustSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AdjustSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            # validate_credentials returns True or raises — it never returns False — so an
            # unexpected status surfaces its real cause instead of a conflated credential error.
            validate_adjust_credentials(config.api_token, config.app_tokens)
            return True, None
        except AdjustCredentialsError as e:
            return False, str(e)
        except (AdjustRetryableError, requests.RequestException):
            # A rate-limit, 5xx, or network blip isn't a bad credential — don't mislabel it.
            return (
                False,
                "Could not reach Adjust to validate credentials. This may be a temporary rate-limit or network issue — please try again.",
            )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AdjustResumeConfig]:
        return ResumableSourceManager[AdjustResumeConfig](inputs, AdjustResumeConfig)

    def source_for_pipeline(
        self,
        config: AdjustSourceConfig,
        resumable_source_manager: ResumableSourceManager[AdjustResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return adjust_source(
            api_token=config.api_token,
            app_tokens=config.app_tokens,
            report=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
