from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleplayconsole import (
    GooglePlayConsoleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.google_play_console import (
    GooglePlayConsoleResumeConfig,
    ServiceAccountKey,
    google_play_console_source,
    parse_package_names,
    validate_credentials as validate_google_play_console_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.settings import (
    DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LOOKBACK_SECONDS,
    MERGE_ONLY,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _service_account_key(config: GooglePlayConsoleSourceConfig) -> ServiceAccountKey:
    return ServiceAccountKey(
        client_email=config.key_file.client_email,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        token_uri=config.key_file.token_uri,
    )


@SourceRegistry.register
class GooglePlayConsoleSource(ResumableSource[GooglePlayConsoleSourceConfig, GooglePlayConsoleResumeConfig]):
    supported_versions = ("v1beta1",)
    default_version = "v1beta1"
    api_docs_url = "https://developers.google.com/play/developer/reporting"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEPLAYCONSOLE

    @property
    def connection_host_fields(self) -> list[str]:
        # app_package_names picks which apps the stored service account key reads, and clearing it
        # selects every app the account can see — so changing it must require re-uploading the key
        # rather than letting an editor who never held it widen the import's reach.
        return ["app_package_names"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Google rejected the service account credentials. Please upload a current JSON key file.",
            "403 Client Error": (
                "The service account cannot read Play Console reporting data. Enable the Play Developer Reporting "
                "API in its Google Cloud project, and give the service account permission to view app quality "
                "data in Play Console."
            ),
            "Google rejected the service account key": (
                "Google rejected the service account key. Check that the key is still active and upload a current one."
            ),
            "Could not sign a token with the uploaded service account key": (
                "The uploaded file is not a usable Google service account key. Please upload the JSON key file "
                "Google Cloud generated, unmodified."
            ),
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_PLAY_CONSOLE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["android", "play store", "vitals", "crash"],
            label="Google Play Console",
            caption="""Sync Android vitals and error reporting from the Play Developer Reporting API: crash and ANR rates, excessive wakeups and stuck wakelocks, slow starts and slow rendering, low-memory kills, plus error issues, error reports, and the anomalies Play detects.

To connect, create a Google Cloud service account and enable the **Play Developer Reporting API** in its project. Then, in Play Console under **Users and permissions**, invite the service account's email and give it access to view app quality data. Upload that service account's JSON key below.

Leave the package names blank to sync every app the service account can see.""",
            iconPath="/static/services/google_play_console.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-play-console",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="key_file",
                        label="Google service account JSON key",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(
                            format=".json",
                            keys=["client_email", "private_key", "private_key_id", "token_uri"],
                        ),
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="app_package_names",
                        label="App package names",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="com.example.app, com.example.other",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GooglePlayConsoleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names=names,
            merge_only=MERGE_ONLY,
            descriptions=DESCRIPTIONS,
        )
        for schema in schemas:
            schema.default_incremental_lookback_seconds = LOOKBACK_SECONDS.get(schema.name)
            schema.detected_primary_keys = PRIMARY_KEYS[schema.name]
        return schemas

    def validate_credentials(
        self,
        config: GooglePlayConsoleSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_google_play_console_credentials(
            _service_account_key(config), self.resolve_api_version(api_version)
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[GooglePlayConsoleResumeConfig]:
        return ResumableSourceManager[GooglePlayConsoleResumeConfig](inputs, GooglePlayConsoleResumeConfig)

    def source_for_pipeline(
        self,
        config: GooglePlayConsoleSourceConfig,
        resumable_source_manager: ResumableSourceManager[GooglePlayConsoleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return google_play_console_source(
            key=_service_account_key(config),
            package_names=parse_package_names(config.app_package_names),
            resource_name=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
