import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser as dateutil_parser
from requests import Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import (
    MAIN_KEY_ONLY_ENDPOINTS,
    TWILIO_ENDPOINTS,
    TwilioEndpointConfig,
)

TWILIO_BASE_URL = "https://api.twilio.com"
TWILIO_API_VERSION = "2010-04-01"
DEFAULT_PAGE_SIZE = 1000

TwilioAuth = tuple[str, str]

# Candidates probed in order at source-create time, when no table has been picked yet. Each one is a
# data resource under /Accounts/{SID}/ rather than /Accounts/{SID}.json itself, because Twilio denies
# the Accounts resource to Standard and Restricted API keys with a 401 (error 20003), and a Standard
# key is the credential this source recommends. Probing the account resource therefore rejected the
# credential type our own caption tells users to create. The three candidates cover one Restricted-key
# permission area each (Messaging, Voice, Phone Numbers), which is what a Restricted key scoped to this
# catalog's high-volume tables can read. Twilio scopes the rest of the catalog separately though, so a
# Restricted key granted only Recordings, say, is denied every candidate and fails here even though the
# table it wants is readable. TWILIO_INVALID_CREDENTIALS_MESSAGE names that as a cause. Widening the
# ladder to cover all 11 tables would make the all-denied path cost 11 sequential requests, so the
# message carries it instead. An account that has never sent a message returns 200 with an empty list,
# so probing real data does not penalize an unused account.
CREDENTIAL_PROBE_ENDPOINTS: tuple[str, ...] = ("messages", "calls", "incoming_phone_numbers")

TWILIO_INVALID_CREDENTIALS_MESSAGE = (
    "Twilio rejected these credentials. Check that the Account SID and secret are correct and have no "
    "extra spaces, and that the API key was created in the same Twilio account as that Account SID. "
    "PostHog connects to api.twilio.com, so a key created in another Twilio region will not work. A "
    "Restricted API key also needs read access to Messages, Calls, or Phone Numbers, which is how "
    "PostHog checks the credential before you pick a table."
)
TWILIO_ACCOUNT_NOT_FOUND_MESSAGE = (
    "Twilio has no account with that Account SID. Copy the Account SID from your Twilio Console "
    "dashboard. It starts with AC."
)
TWILIO_MAIN_KEY_REQUIRED_MESSAGE = (
    "Twilio's Keys resource needs your Auth Token or a Main API key. Standard and Restricted API keys cannot read it."
)
# The schema picker interpolates a reason into its own sentence ("Source credentials cannot read this
# table: {reason}. Grant the missing scope..."), so this has to be a fragment rather than the sentence
# above, and it has to lead with the fix, since no scope grant makes a Standard key work here.
TWILIO_MAIN_KEY_REQUIRED_REASON = "Twilio grants this resource only to your Auth Token or a Main API key"
TWILIO_UNREACHABLE_MESSAGE = "Could not reach Twilio to validate credentials."


@dataclasses.dataclass
class TwilioResumeConfig:
    next_url: str


class TwilioNextPageUriPaginator(BaseNextUrlPaginator):
    """Follow Twilio's body-level ``next_page_uri`` link.

    Twilio returns ``next_page_uri`` as a root-relative path (null/absent on the last page). The
    self-contained next link already carries every query param (PageSize, filters, Page token), so
    we resolve it to an absolute URL on the API host and let ``BaseNextUrlPaginator`` retarget the
    request to it — dropping the original params so they aren't re-appended each page.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            next_page_uri = response.json().get("next_page_uri")
        except Exception:
            next_page_uri = None
        if next_page_uri:
            self._next_url = f"{TWILIO_BASE_URL}{next_page_uri}"
            self._has_next_page = True
        else:
            self._has_next_page = False


def _format_filter_date(value: Any) -> str:
    """Format an incremental watermark as Twilio's day-granular GMT filter value (YYYY-MM-DD).

    Used with an inclusive `>=` filter, so the whole boundary day is re-fetched and de-duplicated
    on `sid` by the pipeline's merge semantics. `bool` is excluded from the numeric branch since it
    subclasses `int`. We raise on anything we can't turn into a real date rather than passing a
    malformed value through, which Twilio would reject mid-sync with the opaque error 20001.
    """
    if isinstance(value, datetime | date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d")
    try:
        return dateutil_parser.parse(str(value)).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError) as e:
        raise ValueError(f"Cannot build a Twilio date filter from incremental value {value!r}") from e


def _build_initial_params(
    config: TwilioEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"PageSize": DEFAULT_PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # Honor the user's chosen cursor field; only filter when it maps to a server-side filter.
        chosen = incremental_field if incremental_field in config.incremental_filter_params else None
        if chosen is None and len(config.incremental_filter_params) == 1:
            chosen = next(iter(config.incremental_filter_params))
        if chosen is not None:
            filter_base = config.incremental_filter_params[chosen]
            # The operator lives in the parameter NAME (e.g. `DateSent>`); the query separator `=`
            # then yields Twilio's documented `DateSent>=<date>` (inclusive, on-or-after) form. The
            # date value must stay plain — inlining the operator into the value triggers error 20001.
            params[f"{filter_base}>"] = _format_filter_date(db_incremental_field_last_value)

    return params


def _build_resource_path(config: TwilioEndpointConfig, account_sid: str) -> str:
    return f"/{TWILIO_API_VERSION}/Accounts/{account_sid}/{config.path}"


def _unexpected_status_message(status: int) -> str:
    return f"Twilio returned an unexpected status ({status}) while validating credentials."


def _endpoint_denied_message(schema_name: str) -> str:
    if schema_name in MAIN_KEY_ONLY_ENDPOINTS:
        return TWILIO_MAIN_KEY_REQUIRED_MESSAGE
    return (
        f"Twilio rejected these credentials for {schema_name}. Check that the Account SID and secret are "
        f"correct, and if this is a Restricted API key, give it read access to {schema_name}."
    )


def _probe_status(auth: TwilioAuth, account_sid: str, schema_name: str) -> int | None:
    """GET one list resource with PageSize=1 and report the HTTP status, or None on transport failure."""
    config = TWILIO_ENDPOINTS[schema_name]
    url = f"{TWILIO_BASE_URL}{_build_resource_path(config, account_sid)}?PageSize=1"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(auth[1],)),
        url,
        auth=HTTPBasicAuth(*auth),
    )
    return status


def validate_credentials(
    auth: TwilioAuth, account_sid: str, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name in TWILIO_ENDPOINTS:
        status = _probe_status(auth, account_sid, schema_name)
        if status == 200:
            return True, None
        if status is None:
            return False, TWILIO_UNREACHABLE_MESSAGE
        # Twilio answers a permission denial with 401 (error 20003) rather than 403, so on this API the
        # two statuses carry the same meaning and neither can be read as a valid credential.
        if status in (401, 403):
            return False, _endpoint_denied_message(schema_name)
        # A 404 is not mapped to "no such account" here the way it is on the create path below: this
        # branch probes one chosen table, so a 404 more likely means that resource is unavailable on
        # the account than that the Account SID is wrong.
        return False, _unexpected_status_message(status)

    # No table chosen yet, so prove the credential can read something rather than asking Twilio to
    # confirm the account itself. See CREDENTIAL_PROBE_ENDPOINTS for why the account resource is unsafe
    # to probe here.
    for candidate in CREDENTIAL_PROBE_ENDPOINTS:
        status = _probe_status(auth, account_sid, candidate)
        if status == 200:
            return True, None
        if status is None:
            return False, TWILIO_UNREACHABLE_MESSAGE
        if status == 404:
            return False, TWILIO_ACCOUNT_NOT_FOUND_MESSAGE
        if status not in (401, 403):
            # A throttle or a server error is not a verdict on the credential, so stop rather than
            # walking the remaining candidates only to report them as invalid.
            return False, _unexpected_status_message(status)

    return False, TWILIO_INVALID_CREDENTIALS_MESSAGE


def check_endpoint_permissions(auth: TwilioAuth, account_sid: str, endpoints: list[str]) -> dict[str, str | None]:
    """Report which tables these credentials cannot read, so the schema picker can disable them."""
    permissions: dict[str, str | None] = dict.fromkeys(endpoints)
    for endpoint in endpoints:
        if endpoint not in MAIN_KEY_ONLY_ENDPOINTS:
            continue
        # Only an outright denial hides the table. A throttle, a server error, or a network blip must
        # not remove a table the credential can actually read.
        if _probe_status(auth, account_sid, endpoint) in (401, 403):
            permissions[endpoint] = TWILIO_MAIN_KEY_REQUIRED_REASON
    return permissions


def twilio_source(
    auth: TwilioAuth,
    account_sid: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TwilioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = TWILIO_ENDPOINTS[endpoint]

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TWILIO_BASE_URL,
            # HTTP basic auth via the framework so the secret is redacted from logs and errors.
            "auth": {"type": "http_basic", "username": auth[0], "password": auth[1]},
            "paginator": TwilioNextPageUriPaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": _build_resource_path(config, account_sid),
                    "params": params,
                    "data_selector": config.response_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `sid`) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(TwilioResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
