from typing import Optional, cast

import requests

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tenjin import TenjinSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.settings import (
    DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.tenjin import (
    TenjinCredentialsError,
    TenjinResumeConfig,
    TenjinRetryableError,
    tenjin_source,
    validate_credentials as validate_tenjin_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TenjinSource(ResumableSource[TenjinSourceConfig, TenjinResumeConfig]):
    lists_tables_without_credentials = True  # static report catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://api-docs.tenjin.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TENJIN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.tenjin.com": "Tenjin rejected your access token. Generate a new token under Automate > API Access Tokens in the Tenjin dashboard and reconnect.",
            "403 Client Error: Forbidden for url: https://api.tenjin.com": "Tenjin denied access. Check that your access token is valid and has the Reporting Metrics API permission.",
            # A 400 means the report request itself is invalid (unknown metric or group_by). The
            # request shape is fixed per table, so retrying it identically can never succeed.
            "400 Client Error: Bad Request for url: https://api.tenjin.com": "Tenjin rejected the report request. Check that your account has access to the requested report and metrics.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TenjinSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=DESCRIPTIONS)

    def validate_credentials(
        self,
        config: TenjinSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            # validate_credentials returns True or raises — it never returns False — so an
            # unexpected status surfaces its real cause instead of a conflated credential error.
            validate_tenjin_credentials(config.api_key)
            return True, None
        except TenjinCredentialsError as e:
            return False, str(e)
        except (TenjinRetryableError, requests.RequestException):
            # A rate-limit, 5xx, or network blip isn't a bad credential. Don't mislabel it.
            return (
                False,
                "Could not reach Tenjin to validate credentials. This may be a temporary rate-limit or network issue. Please try again.",
            )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TenjinResumeConfig]:
        return ResumableSourceManager[TenjinResumeConfig](inputs, TenjinResumeConfig)

    def source_for_pipeline(
        self,
        config: TenjinSourceConfig,
        resumable_source_manager: ResumableSourceManager[TenjinResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return tenjin_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TENJIN,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Tenjin",
            caption="""Enter your Tenjin API access token to pull daily user-acquisition spend, ad revenue, and SKAdNetwork reports into the PostHog Data warehouse.

Generate a token in the Tenjin dashboard under Automate > API Access Tokens. The token must have the Reporting Metrics API permission.

Tenjin's Reporting Metrics API returns metrics aggregated per day, so these tables are daily time series rather than user-level events.""",
            iconPath="/static/services/tenjin.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tenjin",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["mobile attribution", "user acquisition", "mmp"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
