from typing import Optional, cast

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paddle import PaddleSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PaddlePermissionError,
    PaddleResumeConfig,
    PaddleUnreachableError,
    paddle_source,
    validate_credentials as validate_paddle_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.settings import (
    ENDPOINTS as PADDLE_ENDPOINTS,
    INCREMENTAL_FIELDS as PADDLE_INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Shared by the setup probe and by the sync-time error mapping below, so the same refusal reads
# the same way in the source wizard and in the sync error panel.
INVALID_API_KEY_ERROR = (
    "Your Paddle API key is invalid or has been revoked. Create a new API key in your Paddle dashboard, then reconnect."
)
MISSING_PERMISSIONS_ERROR = (
    "Paddle denied the request. Give your API key read permission for the data you want to sync, then reconnect."
)
KEY_CHECK_FAILED_ERROR = "PostHog could not check your Paddle API key. Wait a few minutes, then try again."


@SourceRegistry.register
class PaddleSource(ResumableSource[PaddleSourceConfig, PaddleResumeConfig]):
    api_docs_url = "https://developer.paddle.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    has_managed_hogql_schema = True  # canonical Paddle schema in external_table_definitions

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PADDLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PADDLE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Paddle",
            iconPath="/static/services/paddle.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="paddle_api_key",
                        label="API Key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pdl_live_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://api.paddle.com": "Paddle rejected the request parameters. Please check your source configuration and incremental sync state, then try again.",
            "401 Client Error: Unauthorized for url: https://api.paddle.com": INVALID_API_KEY_ERROR,
            "403 Client Error: Forbidden for url: https://api.paddle.com": MISSING_PERMISSIONS_ERROR,
            # 404 on a list endpoint we know exists means the resource isn't reachable for this
            # account — Paddle Billing isn't enabled, or the API key belongs to a different
            # environment (sandbox vs. production) than the data. Retrying can't change that.
            "404 Client Error: Not Found for url: https://api.paddle.com": "Paddle couldn't find the requested data. This usually means Paddle Billing isn't enabled for your account, or your API key is for a different environment (sandbox vs. production). Check your Paddle account and reconnect with a matching API key.",
        }

    def should_retry_non_retryable_errors(self) -> bool:
        return False

    def validate_credentials(
        self,
        config: PaddleSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            if validate_paddle_credentials(config.paddle_api_key, schema_name):
                return True, None
            return False, INVALID_API_KEY_ERROR
        except PaddlePermissionError:
            return False, MISSING_PERMISSIONS_ERROR
        except PaddleUnreachableError:
            return False, KEY_CHECK_FAILED_ERROR
        except Exception as e:
            # The probe names the endpoint it could not read, which does not help the person
            # filling in the form. Capture the exception so the detail stays available for
            # debugging, and show fixed guidance instead.
            capture_exception(e)
            return False, KEY_CHECK_FAILED_ERROR

    def get_schemas(
        self,
        config: PaddleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(PADDLE_ENDPOINTS, PADDLE_INCREMENTAL_FIELDS, names)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PaddleResumeConfig]:
        return ResumableSourceManager[PaddleResumeConfig](inputs, PaddleResumeConfig)

    def source_for_pipeline(
        self,
        config: PaddleSourceConfig,
        resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return paddle_source(
            api_key=config.paddle_api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
