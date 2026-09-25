import re
from typing import Optional, cast

from django.db import transaction

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    required_parents_from_endpoint_configs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesk import (
    ZendeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.settings import (
    BASE_ENDPOINTS,
    INCREMENTAL_FIELDS as ZENDESK_INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
    SUPPORT_ENDPOINTS,
    ZENDESK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.zendesk import (
    ZendeskCredentials,
    normalize_subdomain,
    validate_credentials,
    zendesk_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

ZENDESK_AUTH_FAILED = (
    "Zendesk authentication failed. Please check your API token and subdomain, or reconnect your Zendesk account."
)


def resolve_zendesk_oauth_token(integration_id: int, team_id: int) -> str:
    """Return a valid access token, refreshing it under a row lock when it is near expiry.

    Zendesk rotates the refresh token on every refresh. The lock stops parallel schema syncs that
    share one integration from spending the same refresh token twice.
    """
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(id=integration_id, team_id=team_id, kind="zendesk")
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired():
            oauth.refresh_access_token()
        token = integration.access_token

    if not token:
        raise ValueError("Zendesk access token not found")
    return token


@SourceRegistry.register
class ZendeskSource(OAuthMixin, SimpleSource[ZendeskSourceConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.zendesk.com/api-reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    has_managed_hogql_schema = True  # canonical Zendesk schema in external_table_definitions

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENDESK

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "404 Client Error: Not Found for url": ZENDESK_AUTH_FAILED,
            "403 Client Error: Forbidden for url": ZENDESK_AUTH_FAILED,
            "401 Client Error": ZENDESK_AUTH_FAILED,
            "Missing Zendesk integration ID": "No Zendesk account is connected. Connect your Zendesk account and try again.",
            "Integration not found": "The linked Zendesk connection no longer exists. Please reconnect your Zendesk account.",
            "Zendesk access token not found": "The Zendesk connection has no access token. Please reconnect your Zendesk account.",
        }

    def _credentials(self, config: ZendeskSourceConfig, team_id: int) -> ZendeskCredentials:
        auth = config.auth_method
        if auth.selection == "api_key":
            if not auth.api_key or not auth.email_address:
                raise ValueError("Enter your Zendesk email address and API token.")
            return ZendeskCredentials(
                subdomain=auth.subdomain or "", email_address=auth.email_address, api_key=auth.api_key
            )

        if not auth.zendesk_integration_id:
            raise ValueError("Missing Zendesk integration ID")
        integration = self.get_oauth_integration(auth.zendesk_integration_id, team_id)
        return ZendeskCredentials(
            subdomain=integration.config.get("subdomain") or "",
            access_token=resolve_zendesk_oauth_token(integration.id, team_id),
        )

    def get_required_parent_schemas(self, schema_name: str) -> list[str]:
        return required_parents_from_endpoint_configs(ZENDESK_ENDPOINTS, schema_name)

    def get_schemas(
        self,
        config: ZendeskSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(BASE_ENDPOINTS)
            + [resource for resource, endpoint_url, data_key, cursor_paginated in SUPPORT_ENDPOINTS]
        ]
        schemas += [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=bool(endpoint_config.incremental_fields),
                supports_append=bool(endpoint_config.incremental_fields),
                incremental_fields=endpoint_config.incremental_fields,
            )
            for endpoint_config in ZENDESK_ENDPOINTS.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: ZendeskSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            credentials = self._credentials(config, team_id)
        except ValueError as e:
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw

        subdomain = normalize_subdomain(credentials.subdomain)
        subdomain_regex = re.compile("^[a-zA-Z0-9-]+$")
        if not subdomain_regex.match(subdomain):
            return False, "Zendesk subdomain is incorrect"

        if validate_credentials(credentials):
            return True, None

        if config.auth_method.selection == "oauth":
            return False, "Zendesk rejected the connection. Reconnect your Zendesk account, then try again."
        return (
            False,
            "Zendesk rejected the credentials. Check the subdomain, email address, and API token are correct, "
            "and that token access is enabled for your account.",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZENDESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            caption="Connect your Zendesk account, or enter a Zendesk API token, to automatically pull your Zendesk support data into the PostHog Data warehouse.",
            iconPath="/static/services/zendesk.png",
            iconClassName="rounded dark:bg-white p-[2px]",
            docsUrl="https://posthog.com/docs/cdp/sources/zendesk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="api_key",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="API token",
                                value="api_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="subdomain",
                                            label="Zendesk subdomain",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="api_key",
                                            label="API key",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                        SourceFieldInputConfig(
                                            name="email_address",
                                            label="Zendesk email address",
                                            type=SourceFieldInputConfigType.EMAIL,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="OAuth",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="zendesk_integration_id",
                                            label="Zendesk account",
                                            required=False,
                                            kind="zendesk",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def source_for_pipeline(self, config: ZendeskSourceConfig, inputs: SourceInputs) -> SourceResponse:
        resource = zendesk_source(
            credentials=self._credentials(config, inputs.team_id),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field_name=inputs.incremental_field,
            source_id=inputs.source_id,
            use_warehouse_parent=inputs.fanout_warehouse_reuse,
        )
        # The original nine endpoints aren't in the declarative catalog; they keep the `id`
        # primary key and ascending sort they have always used.
        endpoint_config = ZENDESK_ENDPOINTS.get(inputs.schema_name)
        response = SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=endpoint_config.primary_key if endpoint_config else ["id"],
            column_hints=resource.column_hints,
            sort_mode=endpoint_config.sort_mode if endpoint_config else "asc",
        )

        partition_key = PARTITION_FIELDS.get(inputs.schema_name, None)
        if partition_key is None and endpoint_config is not None:
            partition_key = endpoint_config.partition_key

        # All partition keys are datetime
        if partition_key:
            response.partition_count = 1
            response.partition_size = 1
            response.partition_mode = "datetime"
            response.partition_format = "week"
            response.partition_keys = [partition_key]

        return response
