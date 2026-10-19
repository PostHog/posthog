from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.flutterwave import (
    MISSING_V3_CREDENTIALS_ERROR,
    MISSING_V4_CREDENTIALS_ERROR,
    NOT_ON_V4_ERROR,
    FlutterwaveResumeConfig,
    flutterwave_source,
    validate_credentials as validate_flutterwave_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.settings import (
    ENDPOINTS,
    FLUTTERWAVE_API_V3,
    FLUTTERWAVE_API_V4,
    INCREMENTAL_FIELDS,
    V4_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flutterwave import (
    FlutterwaveSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FlutterwaveSource(ResumableSource[FlutterwaveSourceConfig, FlutterwaveResumeConfig]):
    codebase_detection = detect(
        env=("^FLUTTERWAVE_", "^FLW_(PUBLIC|SECRET)_KEY$"),
        script_hosts=("checkout.flutterwave.com",),
        npm=("flutterwave-node-v3", "flutterwave-react-v3", "flutterwave-angular-v3"),
        pypi=("flutterwave", "rave-python"),
        composer=(
            "flutterwavedev/flutterwave-v3",
            "flutterwavedev/flutterwave-php",
            "flutterwavedev/flutterwavelaravel",
        ),
        pub=("flutterwave_standard",),
        rubygems=("flutterwave_sdk",),
    )

    # v3 authenticates with a secret key against api.flutterwave.com/v3. v4 runs on its own host with
    # OAuth client credentials, renames some collections, and drops others, so each pin keeps its
    # own credentials, paths, and table set.
    supported_versions = (FLUTTERWAVE_API_V3, FLUTTERWAVE_API_V4)
    default_version = FLUTTERWAVE_API_V4
    api_docs_url = "https://developer.flutterwave.com/v4.0.0/docs/versioning"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLUTTERWAVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FLUTTERWAVE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Flutterwave",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your Flutterwave v4 client ID and client secret to sync your payments data into the PostHog Data warehouse.

You can find them under Settings > API Keys in the [Flutterwave dashboard](https://app.flutterwave.com/dashboard/settings/apis). If the page shows a public key, secret key, and encryption key, you are on v3 keys: click **Switch to v4 live API keys** to see your client ID and client secret. Sources connected before v4 support keep using their v3 secret key.""",
            iconPath="/static/services/flutterwave.png",
            docsUrl="https://posthog.com/docs/cdp/sources/flutterwave",
            fields=cast(
                list[FieldType],
                [
                    # Every field is optional because the pair a source needs depends on its API
                    # version pin; validate_credentials enforces it.
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key (v3 only)",
                        caption="Only needed for sources connected with v3 keys.",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="FLWSECK-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.flutterwave.com": "Your Flutterwave secret key is invalid or has been rotated. Copy the current key from your Flutterwave dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.flutterwave.com": "Your Flutterwave secret key does not have access to this data. Check the key's permissions in your Flutterwave dashboard, then reconnect.",
            "401 Client Error: Unauthorized for url: https://f4bexperience.flutterwave.com": "Flutterwave rejected your client ID and client secret. Copy your current v4 API keys from your Flutterwave dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://f4bexperience.flutterwave.com": "Your Flutterwave v4 API keys do not have access to this data. Check the keys' permissions in your Flutterwave dashboard, then reconnect.",
            # The framework's OAuth2 auth stamps this marker on token failures retrying can't fix
            # (invalid_client and other non-429 4xx from the v4 token endpoint).
            OAUTH2_PERMANENT_ERROR_MARKER: "Flutterwave rejected your client ID and client secret. Copy your current v4 API keys from your Flutterwave dashboard, then reconnect.",
            MISSING_V3_CREDENTIALS_ERROR: "This source uses Flutterwave API v3, which needs a secret key. Add your v3 secret key to the source, then reconnect.",
            MISSING_V4_CREDENTIALS_ERROR: "This source uses Flutterwave API v4, which needs a client ID and client secret. Add your v4 API keys to the source, then reconnect.",
            NOT_ON_V4_ERROR: "Flutterwave API v4 has no endpoint for this table. Switch the table back to API v3 to keep syncing it.",
        }

    def get_schemas(
        self,
        config: FlutterwaveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        endpoints = V4_ENDPOINTS if self.resolve_api_version(api_version) == FLUTTERWAVE_API_V4 else ENDPOINTS
        return build_endpoint_schemas(endpoints, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: FlutterwaveSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_flutterwave_credentials(
            config.secret_key,
            self.resolve_api_version(api_version),
            client_id=config.client_id,
            client_secret=config.client_secret,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FlutterwaveResumeConfig]:
        return ResumableSourceManager[FlutterwaveResumeConfig](inputs, FlutterwaveResumeConfig)

    def source_for_pipeline(
        self,
        config: FlutterwaveSourceConfig,
        resumable_source_manager: ResumableSourceManager[FlutterwaveResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return flutterwave_source(
            secret_key=config.secret_key,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
