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

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleWebfontsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.google_webfonts import (
    google_webfonts_source,
    validate_credentials as validate_google_webfonts_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleWebfontsSource(SimpleSource[GoogleWebfontsSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEWEBFONTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_WEBFONTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Webfonts",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter a Google API key to pull the Google Fonts catalog into the PostHog Data warehouse.

Create an API key in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) and enable the **Web Fonts Developer API** for the project. No OAuth or scopes are required — the API is a public, read-only metadata catalog.
""",
            iconPath="/static/services/google_webfonts.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-webfonts",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="AIza...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.canonical_descriptions import (  # noqa: PLC0415 — lazy import keeps the descriptions off the module import path
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid key returns 400 (`API_KEY_INVALID`) and a missing/unregistered key 403; retrying
            # can never satisfy a credential problem. Match the stable status text and base URL, not the
            # per-request query string (the key is sent as a header, so it never appears in the URL).
            "400 Client Error: Bad Request for url: https://www.googleapis.com/webfonts/v1/webfonts": "Your Google API key is invalid. Create a new key in the Google Cloud Console, enable the Web Fonts Developer API, then reconnect.",
            "403 Client Error: Forbidden for url: https://www.googleapis.com/webfonts/v1/webfonts": "Your Google API key was rejected. Make sure the Web Fonts Developer API is enabled for the key's project, then reconnect.",
        }

    def get_schemas(
        self,
        config: GoogleWebfontsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # The catalog has no server-side timestamp filter, so it's full refresh only.
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
        self, config: GoogleWebfontsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            if validate_google_webfonts_credentials(config.api_key):
                return True, None
        except requests.RequestException:
            return False, "Could not reach the Google Fonts API. Check your network connection and try again."

        return False, "Invalid Google API key"

    def source_for_pipeline(self, config: GoogleWebfontsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return google_webfonts_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
