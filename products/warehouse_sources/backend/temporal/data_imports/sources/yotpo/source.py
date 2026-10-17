from typing import cast

from requests import HTTPError, RequestException

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    UnknownResourceError,
    schema_for_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yotpo import YotpoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.yotpo.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yotpo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.yotpo.yotpo import (
    YotpoAuthenticationError,
    YotpoResumeConfig,
    validate_credentials as validate_yotpo_credentials,
    validate_start_date,
    yotpo_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YotpoSource(ResumableSource[YotpoSourceConfig, YotpoResumeConfig]):
    codebase_detection = detect(
        env=("^YOTPO_", "^(NEXT_PUBLIC|VITE|PUBLIC|REACT_APP)_YOTPO_"),
        script_hosts=("cdn-widgetsrepository.yotpo.com", "staticw2.yotpo.com"),
        npm=("@frontend-sdk/yotpo",),
        composer=(
            "yotpo/module-review",
            "yotpo/module-yotpo-core",
            "yotpo/module-yotpo-reviews",
            "yotpo/module-yotpo-messaging",
            "yotpo/module-yotpo-combined",
            "yotpo/magento2-module-yotpo-loyalty",
            "yotpo/magento2-module-yotpo-core",
            "yotpo/yotpo",
        ),
        rubygems=("yotpo",),
    )

    lists_tables_without_credentials = True
    # Storefront V3 cannot replace the authenticated merchant review and email endpoints.
    api_docs_url = "https://apidocs.yotpo.com/reference/retrieve-all-reviews"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOTPO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Yotpo rejected the app key or API secret": "Check your Yotpo app key and API secret, then reconnect.",
            "Yotpo did not return an access token": "Check your Yotpo API credentials, then reconnect.",
            "401 Client Error": "Your Yotpo access token is invalid or expired. Check your credentials, then reconnect.",
            "403 Client Error": "Yotpo denied access to this table. Check your account's API access.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: YotpoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                description=settings.description,
                detected_primary_keys=list(settings.primary_keys) if settings.primary_keys else None,
            )
            for name, settings in ENDPOINTS.items()
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: YotpoSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.app_key.strip() or not config.api_secret.strip():
            return False, "Enter your Yotpo app key and API secret."
        if schema_name is not None:
            try:
                schema_for_resource(ENDPOINTS, schema_name)
            except UnknownResourceError:
                return False, "This Yotpo table is not supported."
        try:
            validate_start_date(config.start_date)
        except ValueError:
            return False, "Enter a start date in YYYY-MM-DD format that is not in the future."
        try:
            validate_yotpo_credentials(config.app_key, config.api_secret, config.start_date, schema_name)
        except YotpoAuthenticationError as error:
            return False, str(error)
        except HTTPError as error:
            if error.response is not None and error.response.status_code == 401:
                return False, "Yotpo rejected the access token. Check your app key and API secret."
            if error.response is not None and error.response.status_code == 403:
                return False, "Yotpo denied access to this table. Check your account's API access."
            return False, "Yotpo could not validate your credentials. Try again."
        except (RequestException, RESTClientRetryableError, ValueError):
            return False, "Yotpo could not validate your credentials. Try again."
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[YotpoResumeConfig]:
        return ResumableSourceManager(inputs, YotpoResumeConfig)

    def source_for_pipeline(
        self,
        config: YotpoSourceConfig,
        resumable_source_manager: ResumableSourceManager[YotpoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return yotpo_source(
            app_key=config.app_key,
            api_secret=config.api_secret,
            start_date=config.start_date,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YOTPO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Yotpo",
            docsUrl="https://posthog.com/docs/cdp/sources/yotpo",
            iconPath="/static/services/yotpo.png",
            releaseStatus=ReleaseStatus.GA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_key",
                        label="App key (store ID)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date for email data",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YYYY-MM-DD",
                        caption="Email tables include data from this date. Reviews and unsubscribers include all available records.",
                        secret=False,
                    ),
                ],
            ),
        )
