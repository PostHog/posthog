from collections.abc import Callable
from datetime import date
from typing import Any, Optional, cast

import requests

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldCredentialAccountSelectConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads import (
    AppleSearchAdsAuthError,
    AppleSearchAdsClient,
    AppleSearchAdsCredentials,
    AppleSearchAdsResumeConfig,
    apple_search_ads_source,
    readable_ad_accounts,
    token_exchange_error_message,
    validate_credentials as validate_apple_search_ads_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.oauth import (
    apple_ads_access_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.settings import (
    APPLE_ADS_API_VERSION_V1,
    APPLE_SEARCH_ADS_API_VERSION_V5,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REPORT_ENDPOINTS,
    REPORT_LOOKBACK_SECONDS,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    CredentialAccountsMixin,
    OAuthMixin,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applesearchads import (
    AppleSearchAdsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppleSearchAdsSource(
    ResumableSource[AppleSearchAdsSourceConfig, AppleSearchAdsResumeConfig],
    CredentialAccountsMixin[AppleSearchAdsSourceConfig],
    OAuthMixin,
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = (APPLE_SEARCH_ADS_API_VERSION_V5, APPLE_ADS_API_VERSION_V1)
    default_version = APPLE_ADS_API_VERSION_V1
    # Apple sunsets the Campaign Management API 5 on 2027-01-26, after which its endpoints stop
    # serving. A pinned source cannot be repinned for it: the Platform API scopes requests to
    # an ad account id, which is not derivable from the stored organization id.
    deprecated_versions = (VersionDeprecation(version=APPLE_SEARCH_ADS_API_VERSION_V5, sunset_at=date(2027, 1, 26)),)
    api_docs_url = "https://developer.apple.com/documentation/apple-ads-platform-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPLESEARCHADS

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored private key is sent against whichever ad account (Platform API) or
        # organization (v5) is configured, so changing either retargets the saved credential at a
        # different Apple account — force secret re-entry on a change to either.
        return ["ad_account_id", "org_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://appleid.apple.com/auth/oauth2/token": "Apple rejected the signed client secret. Check your client ID, team ID, key ID and private key.",
            "401 Client Error: Unauthorized for url: https://appleid.apple.com/auth/oauth2/token": "Apple rejected the signed client secret. Check your client ID, team ID, key ID and private key.",
            "401 Client Error: Unauthorized for url: https://api.ads.apple.com": "Apple rejected the access token. Your API client may have been removed. Create a new one in Apple Ads and reconnect this source.",
            "403 Client Error: Forbidden for url: https://api.ads.apple.com": "Apple denied access to this ad account. Check that the API user has the API Account Read Only role for the ad account ID you entered.",
            "404 Client Error: Not Found for url: https://api.ads.apple.com": "Apple could not find this ad account. Check the ad account ID, which you can read from `adAccount.id` in Apple's Get User ACL endpoint.",
            "400 Client Error: Bad Request for url: https://api.searchads.apple.com": "Apple rejected a reporting request. Some campaign types don't support keyword reporting. If the error persists, remove the keyword_report table or check your campaign types in Apple Ads.",
            # Apple occasionally returns an empty HTTP reason phrase for the same 400 condition.
            "400 Client Error:  for url: https://api.searchads.apple.com": "Apple rejected a reporting request. Some campaign types don't support keyword reporting. If the error persists, remove the keyword_report table or check your campaign types in Apple Ads.",
            "401 Client Error: Unauthorized for url: https://api.searchads.apple.com": "Apple Search Ads rejected the access token. Your API key may have been revoked. Generate a new one and reconnect this source.",
            "403 Client Error: Forbidden for url: https://api.searchads.apple.com": "Apple Search Ads denied access to this organization. Check that the API user has at least read access to the organization ID you entered.",
            "Could not sign the Apple Ads client secret": "The private key isn't a valid unencrypted EC (P-256) PEM. Paste the key you generated for your Apple Ads API client and reconnect.",
        }

    def get_retryable_errors(self) -> set[str]:
        # Apple's transport already retries these statuses in-process (see the
        # `status_forcelist` on `APPLE_SEARCH_ADS_RETRY`) with backoff, so one only reaches
        # here once that budget is exhausted — Apple is rate-limiting us (429) or its API is
        # briefly unavailable (5xx). Both are transient and self-recovering, so let Temporal
        # retry the whole activity. Unlike the shared REST engine, this source has its own
        # client, so `raise_for_status()` surfaces a plain `requests.HTTPError` that no
        # `RESTClientRetryableError` type-check catches; without this classification the
        # benign, self-recovering failure is logged at `exception` and reported as an
        # unclassified error every run. Match the code-anchored fragment, not the volatile
        # reason phrase or per-request URL.
        return {
            "429 Client Error",
            "500 Server Error",
            "502 Server Error",
            "503 Server Error",
            "504 Server Error",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPLESEARCHADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Apple Ads",
            caption="""Connect your Apple Ads account, formerly Apple Search Ads, to pull campaigns, ad groups, keywords and daily performance into the PostHog Data warehouse.

Choose **Sign in with Apple** and authorize PostHog. Apple sends you back here, and the **Ad account** list fills with the accounts you can read.

Either way, your Apple Ads user needs an API role first, or the connection reads nothing. An account admin grants one in [Apple Ads](https://ads.apple.com) under **Account settings > User management**.

The **API key pair** option is for accounts that run their own API client, and for sources still on Apple's Campaign Management API 5. It needs a key pair you generate and register yourself:

1. Generate an EC P-256 key pair. On macOS or Linux, run `openssl ecparam -genkey -name prime256v1 -noout -out private-key.pem` and then `openssl ec -in private-key.pem -pubout -out public-key.pem`.
2. Signed in as a user with an API role, open **Account settings > API**, paste the contents of `public-key.pem` into the public key field and save. Saving the key creates the client. An account admin who holds no API role will not see that field.
3. Apple then shows the client ID, team ID and key ID above the field. Enter those below, along with the contents of `private-key.pem`.

PostHog stores every credential encrypted. With a key pair, PostHog signs a short-lived token on each sync and never stores that token.

Reporting tables use daily granularity, which Apple serves for the last 90 days only.""",
            permissionsCaption="""Assign the **API Account Read Only** role to the Apple Ads user who sets up the connection, under **Account settings > User management**. Apple attaches API roles to users, not to clients, so this applies to both authentication types. That role grants read access to the campaign data these tables are built from. Pick it rather than the campaign group **API Read Only**, which covers a single campaign group. The **API Account Manager** role also works if you already use it.""",
            iconPath="/static/services/apple_search_ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/apple-search-ads",
            releaseStatus=ReleaseStatus.BETA,
            # "Apple Search Ads" is the former product name, kept so the catalog still finds
            # this source under what Apple used to call it.
            keywords=["apple search ads", "asa", "app store ads", "search ads", "apple maps ads"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        # Signing in is the default because it asks the customer for nothing: Apple
                        # grants the token to PostHog's own service provider registration.
                        defaultValue="oauth",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Sign in with Apple",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="apple_ads_integration_id",
                                            label="Apple Ads account",
                                            required=False,
                                            kind="apple-ads",
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="API key pair",
                                value="key_pair",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="client_id",
                                            label="Client ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            # The branch fields are optional at the form level
                                            # because the other branch leaves them empty.
                                            # `validate_credentials` requires the set the chosen
                                            # branch needs.
                                            required=False,
                                            placeholder="SEARCHADS.27478e17-...",
                                            caption="Apple shows this after you save the public key for your API client.",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="apple_team_id",
                                            label="Team ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="SEARCHADS.6f0a1b2c-...",
                                            caption="Apple shows this next to the client ID. It often matches the client ID.",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="key_id",
                                            label="Key ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="a1b2c3d4-...",
                                            caption="Apple shows this next to the client ID.",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="private_key",
                                            label="Private key",
                                            type=SourceFieldInputConfigType.TEXTAREA,
                                            required=False,
                                            placeholder="-----BEGIN EC PRIVATE KEY-----",
                                            caption="The unencrypted EC P-256 private key matching the public key you uploaded to Apple.",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldCredentialAccountSelectConfig(
                        name="ad_account_id",
                        label="Ad account ID",
                        # Optional at the form level because a source pinned to Apple's older API
                        # needs the organization ID below instead. `validate_credentials` requires
                        # whichever one the source's API version uses.
                        required=False,
                        placeholder="123456789",
                        # Ordered after the four fields it names, because the lookup signs a token
                        # with them. Apple exposes the ad account id nowhere in its UI, so without
                        # this the only way to read one is to call the ACL endpoint by hand.
                        credentialFields=["client_id", "apple_team_id", "key_id", "private_key"],
                        # Both auth branches reach the same ACL endpoint, so one picker serves both:
                        # the grant when the user signed in, the typed-in key pair otherwise.
                        integrationField="apple_ads_integration_id",
                        caption="Connect your account above, or fill in the credentials, and this lists the ad accounts they can read. You can also type one in: it is `adAccount.id` from Apple's Get User ACL endpoint, `GET https://api.ads.apple.com/v1/acls`, and it is not the same as your organization ID.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Report start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2026-06-01",
                        caption="Earliest day to pull reporting for. Apple serves daily reporting for the last 90 days, so anything older is read from that day instead.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="123456",
                        caption="Only for sources still on Apple's Campaign Management API 5, which Apple stops serving on 26 January 2027. Those use the API key pair option. Leave this empty and pick an ad account instead.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AppleSearchAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        endpoints = endpoints_for_version(self.resolve_api_version(api_version))
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=ENDPOINT_DESCRIPTIONS,
            # Every incremental run re-reads a trailing window of already-imported days, so
            # these tables have to merge on their primary key; appending would duplicate rows.
            merge_only=REPORT_ENDPOINTS,
        )

        for schema in schemas:
            # Apple keeps revising the last few days of reporting data (ingestion delay plus
            # attribution), so an incremental run re-reads a trailing window instead of
            # trusting the frozen watermark.
            if endpoints[schema.name].partition_key is not None:
                schema.default_incremental_lookback_seconds = REPORT_LOOKBACK_SECONDS

        return schemas

    @staticmethod
    def _normalize_job_inputs(job_inputs: dict) -> dict:
        """Wrap a flat payload in the auth branch the config expects.

        Two callers send one: a key-pair row stored before the auth selector existed, and the
        connect form's ad account picker, which posts the single field it holds rather than the
        branch around it. Reading an integration id as key-pair material leaves the signing path
        with no private key, so the id decides the branch.
        """
        if "auth_method" in job_inputs:
            return job_inputs

        normalized = dict(job_inputs)
        integration_id = job_inputs.get("apple_ads_integration_id")
        if integration_id:
            normalized["auth_method"] = {
                "selection": "oauth",
                "apple_ads_integration_id": integration_id,
            }
            return normalized

        normalized["auth_method"] = {
            "selection": "key_pair",
            "client_id": job_inputs.get("client_id"),
            "apple_team_id": job_inputs.get("apple_team_id"),
            "key_id": job_inputs.get("key_id"),
            "private_key": job_inputs.get("private_key"),
        }
        return normalized

    def parse_config(self, job_inputs: dict) -> AppleSearchAdsSourceConfig:
        return self._config_class.from_dict(self._normalize_job_inputs(job_inputs))

    def validate_config(self, job_inputs: dict) -> tuple[bool, list[str]]:
        return self._config_class.validate_dict(self._normalize_job_inputs(job_inputs))

    def serialize_config(self, config: AppleSearchAdsSourceConfig) -> dict[str, Any]:
        serialized = config.to_dict()
        if config.auth_method.selection == "key_pair":
            serialized.update(
                client_id=config.auth_method.client_id,
                apple_team_id=config.auth_method.apple_team_id,
                key_id=config.auth_method.key_id,
                private_key=config.auth_method.private_key,
            )
        return serialized

    def validate_credentials(
        self,
        config: AppleSearchAdsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        resolved_version = self.resolve_api_version(api_version)
        if self._uses_oauth(config):
            if resolved_version != APPLE_ADS_API_VERSION_V1:
                return False, (
                    "Signing in with Apple only works with the Apple Ads Platform API. Reconnect "
                    "this source with an API key pair, or move it off Campaign Management API 5."
                )
        elif not config.auth_method.private_key:
            if config.auth_method.selection == "oauth":
                return False, "Connect your Apple Ads account, or switch to the API key pair option."
            return False, "Enter the client ID, team ID, key ID and private key from your Apple Ads API client."

        try:
            token_provider = self._token_provider(config, team_id)
        except ValueError:
            return False, "The connected Apple Ads account no longer exists. Connect it again."

        return validate_apple_search_ads_credentials(
            self._credentials(config),
            resolved_version,
            schema_name,
            token_provider=token_provider,
        )

    def get_credential_accounts(
        self, config: AppleSearchAdsSourceConfig, team_id: int, api_version: str | None = None
    ) -> list[IntegrationAccount]:
        """The ad accounts this source's credentials can read.

        Serves both auth branches: a connected Apple Ads account reaches the ACL endpoint with its
        own bearer token, a typed-in key pair signs one. Only the Platform API scopes on an ad
        account; a source pinned to the older Campaign Management API takes an organization ID,
        which Apple does show in its UI, so there is nothing to list.
        """
        resolved_version = self.resolve_api_version(api_version)
        # Checked before authenticating: a token exchange to then list nothing still spends the
        # customer's Apple rate-limit budget on every keystroke that completes the form.
        if resolved_version != APPLE_ADS_API_VERSION_V1:
            return []

        try:
            token_provider = self._token_provider(config, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The connected Apple Ads account no longer exists. Connect it again."
            ) from e

        client = AppleSearchAdsClient(self._credentials(config), resolved_version, token_provider=token_provider)
        try:
            client.authenticate()
        except AppleSearchAdsAuthError as e:
            raise IntegrationAccountListingError(str(e)) from e
        except requests.RequestException as e:
            raise IntegrationAccountListingError(token_exchange_error_message(e)) from e

        # None means the ACL lookup itself failed. The picker has no better answer than an empty
        # list either way, and its field stays free text, so the user can still type an id.
        accounts = readable_ad_accounts(client, resolved_version) or []
        return [IntegrationAccount(value=account.id, display_name=account.name or account.id) for account in accounts]

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppleSearchAdsResumeConfig]:
        # Entity and report endpoints store incompatible checkpoint shapes, so keep each
        # endpoint's state in its own Redis slot.
        return ResumableSourceManager[AppleSearchAdsResumeConfig](inputs, AppleSearchAdsResumeConfig).with_namespace(
            inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: AppleSearchAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppleSearchAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return apple_search_ads_source(
            credentials=self._credentials(config),
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            request_logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            start_date=config.start_date,
            token_provider=self._token_provider(config, inputs.team_id),
        )

    @staticmethod
    def _uses_oauth(config: AppleSearchAdsSourceConfig) -> bool:
        """Whether this source authenticates through an Apple Ads grant rather than a key pair.

        The stored integration id is the test, not `auth_method.selection`. Migration 0172 names
        the branch on every source that predates the sign-in path, but a source holds its key
        material flat until that migration runs, and a flat source parses with the branch's
        generated default, which is the sign-in option.
        """
        return bool(config.auth_method.apple_ads_integration_id)

    def _token_provider(self, config: AppleSearchAdsSourceConfig, team_id: int) -> Optional[Callable[[], str]]:
        """Bearer-token source for the client, or None to let it sign one from the key pair."""
        if not self._uses_oauth(config):
            return None

        integration_id = config.auth_method.apple_ads_integration_id
        assert integration_id is not None
        integration = self.get_oauth_integration(integration_id, team_id)
        if integration.kind != "apple-ads":
            raise ValueError(f"Integration {integration_id} is not an Apple Ads integration")
        # Resolved per call, not once: Apple's access tokens live an hour, which a backfill
        # routinely outlives, and the client re-authenticates on a 401.
        return lambda: apple_ads_access_token(integration)

    @staticmethod
    def _credentials(config: AppleSearchAdsSourceConfig) -> AppleSearchAdsCredentials:
        return AppleSearchAdsCredentials(
            client_id=config.auth_method.client_id or "",
            team_id=config.auth_method.apple_team_id or "",
            key_id=config.auth_method.key_id or "",
            private_key=config.auth_method.private_key or "",
            org_id=config.org_id,
            ad_account_id=config.ad_account_id,
        )
