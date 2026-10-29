from typing import Optional, cast

import requests

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    UNVERSIONED_API_VERSION,
    FieldType,
    ResumableSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.polar import PolarSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.polar.polar import (
    POLAR_VERSION_2026_10,
    PolarPermissionError,
    PolarResumeConfig,
    polar_source,
    validate_credentials as validate_polar_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polar.settings import ENDPOINTS as POLAR_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PolarSource(ResumableSource[PolarSourceConfig, PolarResumeConfig]):
    codebase_detection = detect(
        env=("^POLAR_",),
        npm=("@polar-sh/sdk", "@polar-sh/nextjs", "@polar-sh/better-auth", "@polar-sh/checkout", "@polar-sh/ui"),
        pypi=("polar-sdk",),
        composer=("polar-sh/sdk",),
        go=("github.com/polarsource/polar-go",),
    )

    supported_versions = (UNVERSIONED_API_VERSION, POLAR_VERSION_2026_10)
    default_version = POLAR_VERSION_2026_10
    api_docs_url = "https://docs.polar.sh/api-reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POLAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.POLAR,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Polar",
            caption=(
                "Connect your Polar.sh account using an "
                "[Organization Access Token](https://docs.polar.sh/integrate/oat) "
                "to sync customers, products, orders, subscriptions, and more.\n\n"
                "**Required scopes:** `benefits:read`, `checkouts:read`, `customers:read`, "
                "`orders:read`, `organizations:read`, `products:read`, `refunds:read`, "
                "`subscriptions:read`."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/polar",
            iconPath="/static/services/polar.png",
            iconClassName="rounded dark:bg-white p-[2px]",
            featureFlag="dwh_polar",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="polar_api_key",
                        label="Organization Access Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="polar_oat_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.polar.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.polar.sh": "Your Polar Organization Access Token is invalid or expired. Please generate a new token in Polar and reconnect.",
            "403 Client Error: Forbidden for url: https://api.polar.sh": "Your Polar Organization Access Token does not have the required permissions. Please check the token's scopes in Polar and reconnect.",
            # Polar answers a removed or unknown `Polar-Version` with a 404; the list endpoints are static.
            "404 Client Error: Not Found for url: https://api.polar.sh": "The Polar API version this source uses is no longer supported by Polar. Please contact support to move it to a newer version.",
        }

    def get_retryable_errors(self) -> set[str]:
        # `get_rows` calls `response.raise_for_status()` directly rather than through the shared REST
        # engine, so a 5xx that survives `_get_polar_session`'s `DEFAULT_RETRY` (status_forcelist
        # 429/500/502/503/504) isn't wrapped as a retryable exception type either — it's still a
        # transient Polar-side outage, and Temporal retries the whole activity next. Match status,
        # reason and host, not the path or query string, since every endpoint and page can hit this.
        # Mirrors Microsoft Clarity's and Checkout.com's equivalent classification of the same
        # already-retried status codes.
        return {
            "500 Server Error: Internal Server Error for url: https://api.polar.sh",
            "502 Server Error: Bad Gateway for url: https://api.polar.sh",
            "503 Server Error: Service Unavailable for url: https://api.polar.sh",
            "504 Server Error: Gateway Timeout for url: https://api.polar.sh",
        }

    def validate_credentials(
        self, config: PolarSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        try:
            validate_polar_credentials(config.polar_api_key, self.resolve_api_version(api_version), schema_name)
            return True, None
        except PolarPermissionError as e:
            return False, f"Polar Organization Access Token lacks permissions: {e}"
        except requests.exceptions.HTTPError as e:
            # A failed probe surfaces via raise_for_status(): its str() leaks the full request URL
            # (with query params) and tells the user nothing to act on. Map the status instead.
            status_code = e.response.status_code if e.response is not None else None
            if status_code == 401:
                return (
                    False,
                    "Your Polar Organization Access Token is invalid or expired. Please generate a new token in Polar and reconnect.",
                )
            if status_code == 403:
                return (
                    False,
                    "Your Polar Organization Access Token does not have the required permissions. Please check the token's scopes in Polar and reconnect.",
                )
            return (
                False,
                f"Polar returned an unexpected error (HTTP {status_code}) while validating your token. Please try again.",
            )
        except Exception as e:
            return False, str(e)

    def get_schemas(
        self,
        config: PolarSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Full refresh only — Polar's list endpoints accept no server-side timestamp filter,
        # so an "incremental" sync would still fetch every page. We surface that honestly by
        # not offering the incremental option in the wizard.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in POLAR_ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PolarResumeConfig]:
        return ResumableSourceManager[PolarResumeConfig](inputs, PolarResumeConfig)

    def source_for_pipeline(
        self,
        config: PolarSourceConfig,
        resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return polar_source(
            api_key=config.polar_api_key,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )
