from typing import Optional, cast

import requests
from google.auth.exceptions import RefreshError

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.google_analytics import (
    GoogleAnalyticsResumeConfig,
    get_property_metadata,
    google_analytics_session,
    google_analytics_source,
    normalize_property_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.settings import (
    GOOGLE_ANALYTICS_INCREMENTAL_FIELD,
    GOOGLE_ANALYTICS_REPORT_SCHEMAS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleAnalyticsSource(ResumableSource[GoogleAnalyticsSourceConfig, GoogleAnalyticsResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEANALYTICS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Google Analytics connection is invalid or expired. Please reconnect your account.",
            "403 Client Error": "PostHog is not authorized to read this Google Analytics property. Please make sure the connected Google account has access to the property.",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "Insufficient permissions. Please reconnect your Google Analytics account with the required scopes.",
        }

    def get_schemas(
        self,
        config: GoogleAnalyticsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=[GOOGLE_ANALYTICS_INCREMENTAL_FIELD],
                description=schema["description"],
                should_sync_default=schema["should_sync_default"],
            )
            for name, schema in GOOGLE_ANALYTICS_REPORT_SCHEMAS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GoogleAnalyticsResumeConfig]:
        return ResumableSourceManager[GoogleAnalyticsResumeConfig](inputs, GoogleAnalyticsResumeConfig)

    def source_for_pipeline(
        self,
        config: GoogleAnalyticsSourceConfig,
        resumable_source_manager: ResumableSourceManager[GoogleAnalyticsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return google_analytics_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    def validate_credentials(
        self,
        config: GoogleAnalyticsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        property_id = normalize_property_id(config.property_id)
        if not property_id.isdigit():
            return (
                False,
                f"'{config.property_id}' is not a valid GA4 property ID. Use the numeric ID from "
                "Google Analytics admin settings (e.g. '123456789' or 'properties/123456789').",
            )

        try:
            session = google_analytics_session(config.google_analytics_integration_id, team_id)
        except Exception as e:
            return False, f"Could not load Google Analytics credentials: {e}"

        try:
            get_property_metadata(session, property_id)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                return (
                    False,
                    f"Google Analytics rejected the credentials for property '{property_id}'. Please reconnect "
                    "your account and ensure it has read access to the property.",
                )
            if status == 404:
                return (
                    False,
                    f"GA4 property '{property_id}' was not found. Verify the numeric property ID in "
                    "Google Analytics admin settings.",
                )
            return False, f"Failed to read Google Analytics property metadata: {e}"
        except RefreshError:
            # Raised while AuthorizedSession refreshes the OAuth access token (e.g. invalid_scope or
            # invalid_grant): the stored token is missing the required permissions, or has expired or
            # been revoked. Retrying can't recover it — the raw RefreshError repr is meaningless to
            # users, so guide them to reconnect.
            return (
                False,
                "PostHog could not authenticate with Google Analytics. Your connection may have "
                "expired or is missing the required permissions. Please reconnect your Google "
                "account and grant access to Google Analytics.",
            )
        except Exception as e:
            return False, f"Failed to read Google Analytics property metadata: {e}"

        return True, None

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_ANALYTICS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["ga4", "ga"],
            label="Google Analytics",
            caption=(
                "Connect a Google Analytics 4 property to sync daily report data (users, sessions, page views, "
                "devices, locations, traffic sources, and events). Requires a Google account with read access "
                "to the GA4 property."
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-google-analytics",
            iconPath="/static/services/google_analytics.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-analytics",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="google_analytics_integration_id",
                        label="Google Analytics account",
                        required=True,
                        kind="google-analytics",
                        requiredScopes="https://www.googleapis.com/auth/analytics.readonly",
                    ),
                    SourceFieldInputConfig(
                        name="property_id",
                        label="Property ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456789",
                        caption=(
                            "The numeric GA4 property ID, found in Google Analytics under "
                            "Admin → Property settings → Property details."
                        ),
                        secret=False,
                    ),
                ],
            ),
        )
