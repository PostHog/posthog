import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    BearerTokenAuthConfig,
    ClientConfig,
    EndpointResource,
    OAuth2AuthConfig,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.settings import (
    BANK_COUNTRIES,
    BILL_PAYMENT_STATUSES,
    FLUTTERWAVE_API_V4,
    FLUTTERWAVE_ENDPOINTS,
    FLUTTERWAVE_V4_ENDPOINTS,
    WALLET_STATEMENT_TYPES,
    FlutterwaveV4EndpointConfig,
)

FLUTTERWAVE_API_HOST = "https://api.flutterwave.com"
# v4 is served from its own production host with no version path segment.
FLUTTERWAVE_V4_API_HOST = "https://f4bexperience.flutterwave.com"
FLUTTERWAVE_V4_TOKEN_URL = "https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token"

MISSING_V3_CREDENTIALS_ERROR = "Flutterwave API v3 needs a secret key"
MISSING_V4_CREDENTIALS_ERROR = "Flutterwave API v4 needs a client ID and client secret"
NOT_ON_V4_ERROR = "This Flutterwave table is not available on API v4"

VALIDATE_TIMEOUT = 10

# Floor of the mandatory date window on /transactions. Flutterwave has no merchant records that
# predate the platform, so this pulls the full history on every sync without having to guess when the
# account was opened.
EARLIEST_WINDOW_START = "2016-01-01"

# The API's `from`/`to` window is day-granular and Flutterwave does not expose the account's
# reporting timezone, so the window end is padded by a day rather than pinned to UTC today. Pinning
# it would clip records booked "today" in a timezone ahead of UTC.
WINDOW_END_PADDING_DAYS = 1

# v3 answers "no records in this range" on some list endpoints with HTTP 400 rather than an empty
# `data` array, so those bodies are treated as an empty page instead of failing the sync. The match
# is deliberately narrow: a genuine parameter error ("page parameter must be a positive integer")
# does not carry this wording and still raises. Both cases are listed because the substring match is
# case sensitive and v3 is inconsistent about capitalizing "found".
_NO_RECORDS_RESPONSE_ACTIONS: list[ResponseAction] = [
    {"status_code": 400, "content": "found", "action": "ignore"},
    {"status_code": 400, "content": "Found", "action": "ignore"},
]


@dataclasses.dataclass(frozen=False)
class FlutterwaveResumeConfig:
    # 1-based page number to resume pagination from. 1 means "start from the beginning".
    next_page: int = 1
    # Opaque `next` cursor for the v4 cursor-paginated endpoints. A separate field so a page number
    # saved by a page-numbered endpoint is never sent as a cursor, and the reverse.
    next_cursor: Optional[str] = None
    # Country or currency that `next_page` belongs to, for endpoints queried once per value.
    fan_out_value: Optional[str] = None


class FlutterwaveCursorPaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(cursor_path="data.cursor.next", cursor_param="next", raise_on_repeated_cursor=True)

    def update_state(self, response: Any, data: Optional[list[Any]] = None) -> None:
        # v4 reports `has_more_items` next to the cursor. Check it first, so a last page that
        # repeats or still carries a cursor ends the list instead of tripping the repeat guard.
        try:
            has_more = response.json()["data"]["cursor"].get("has_more_items")
        except Exception:
            has_more = None
        if has_more is False:
            self._has_next_page = False
            return
        super().update_state(response, data)


def base_url(api_version: str) -> str:
    if api_version == FLUTTERWAVE_API_V4:
        return FLUTTERWAVE_V4_API_HOST
    return f"{FLUTTERWAVE_API_HOST}/{api_version}"


def _secret_values(secret_key: Optional[str], client_secret: Optional[str]) -> tuple[str, ...]:
    return tuple(value for value in (secret_key, client_secret) if value)


def _auth_config(
    api_version: str, secret_key: Optional[str], client_id: Optional[str], client_secret: Optional[str]
) -> BearerTokenAuthConfig | OAuth2AuthConfig:
    if api_version == FLUTTERWAVE_API_V4:
        if not client_id or not client_secret:
            raise ValueError(MISSING_V4_CREDENTIALS_ERROR)
        # v4 tokens live for ten minutes; the framework's OAuth2 auth re-mints them during a sync.
        return {
            "type": "oauth2",
            "token_url": FLUTTERWAVE_V4_TOKEN_URL,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        }
    if not secret_key:
        raise ValueError(MISSING_V3_CREDENTIALS_ERROR)
    return {"type": "bearer", "token": secret_key}


def _window_end() -> str:
    return (datetime.now(UTC).date() + timedelta(days=WINDOW_END_PADDING_DAYS)).isoformat()


def _mint_v4_access_token(client_id: str, client_secret: str) -> Optional[str]:
    # capture=False keeps the token response out of HTTP samples; allow_redirects=False so a 3xx
    # cannot send the client secret to another host.
    session = make_tracked_session(redact_values=(client_secret,), capture=False, allow_redirects=False)
    response = session.post(
        FLUTTERWAVE_V4_TOKEN_URL,
        data={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
        timeout=VALIDATE_TIMEOUT,
    )
    if response.status_code != 200:
        return None
    token = response.json().get("access_token")
    return token if isinstance(token, str) and token else None


def _validate_v4_credentials(client_id: Optional[str], client_secret: Optional[str]) -> tuple[bool, str | None]:
    if not client_id or not client_secret:
        return False, "Enter your Flutterwave v4 client ID and client secret."
    invalid = "Invalid Flutterwave client ID or client secret. Check your v4 API keys in your Flutterwave dashboard and try again."
    try:
        token = _mint_v4_access_token(client_id, client_secret)
    except Exception:
        return False, "Could not reach the Flutterwave API. Try again in a few minutes."
    if token is None:
        return False, invalid
    # /settlements needs no required params, so it confirms the token can read account data.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_secret, token), capture=False),
        f"{FLUTTERWAVE_V4_API_HOST}/settlements",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    # The token mint already proved the credentials, so a 403 only means these keys cannot read
    # settlements. That must not block connecting the tables they can read.
    if ok or status == 403:
        return True, None
    if status == 401:
        return False, invalid
    return False, "Could not reach the Flutterwave API. Try again in a few minutes."


def validate_credentials(
    secret_key: Optional[str],
    api_version: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> tuple[bool, str | None]:
    if api_version == FLUTTERWAVE_API_V4:
        return _validate_v4_credentials(client_id, client_secret)
    if not secret_key:
        return False, "Enter your Flutterwave secret key."
    # /subaccounts is the cheapest authenticated probe: no required params, a small body, and it only
    # needs the account's secret key. Its response also carries subaccount bank details, so keep it
    # out of the HTTP diagnostic sample store (capture=False).
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(secret_key,), capture=False),
        f"{base_url(api_version)}/subaccounts",
        headers={"Authorization": f"Bearer {secret_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Flutterwave secret key. Check the key in your Flutterwave dashboard and try again."
    if status == 400:
        # The key was accepted; v3 uses 400 for "no subaccounts on this account", which is not a
        # credential problem.
        return True, None
    return False, "Could not reach the Flutterwave API. Try again in a few minutes."


def _v3_endpoint_config(endpoint: str, fan_out: Optional[dict[str, str]] = None) -> Endpoint:
    config = FLUTTERWAVE_ENDPOINTS[endpoint]

    path = config.path
    params: dict[str, Any] = dict(config.params)
    for name, value in (fan_out or {}).items():
        placeholder = f"{{{name}}}"
        if placeholder in path:
            path = path.replace(placeholder, value)
        else:
            params[name] = value
    if config.requires_date_window:
        # /transactions requires `from`/`to`, so a full refresh sends the whole history window: the
        # earliest-possible floor through today (padded a day for timezones ahead of UTC).
        params["from"] = EARLIEST_WINDOW_START
        params["to"] = _window_end()

    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": config.data_selector,
        # Paged v3 list endpoints count pages from 1 and report the page count under
        # `page_info.total_pages`, which stops pagination without paying an extra empty page.
        # Page size is left to the API: v3 documents no maximum, and an over-cap value 4xxs.
        "paginator": PageNumberPaginator(base_page=1, total_path=config.total_pages_path)
        if config.total_pages_path is not None
        else SinglePagePaginator(),
        "response_actions": _NO_RECORDS_RESPONSE_ACTIONS,
    }
    return endpoint_config


def _wallet_currencies(client: ClientConfig, team_id: int, job_id: str) -> list[str]:
    # /wallet/statement requires a currency, and /balances lists every currency the wallet holds,
    # including ones at zero that can still have history.
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [
            {
                "name": "balances",
                "endpoint": {"path": "/balances", "data_selector": "data", "paginator": SinglePagePaginator()},
            }
        ],
    }
    currencies: set[str] = set()
    for page in rest_api_resource(rest_config, team_id, job_id, None):
        for row in page if isinstance(page, list) else [page]:
            currency = row.get("currency")
            if isinstance(currency, str) and currency:
                currencies.add(currency)
    return sorted(currencies)


def _v3_fan_out_values(endpoint: str, client: ClientConfig, team_id: int, job_id: str) -> list[dict[str, str]]:
    fan_out_params = FLUTTERWAVE_ENDPOINTS[endpoint].fan_out_params
    if fan_out_params == ("country",):
        return [{"country": country} for country in BANK_COUNTRIES]
    if fan_out_params == ("status",):
        return [{"status": status} for status in BILL_PAYMENT_STATUSES]
    if fan_out_params == ("currency", "type"):
        return [
            {"currency": currency, "type": statement_type}
            for currency in _wallet_currencies(client, team_id, job_id)
            for statement_type in WALLET_STATEMENT_TYPES
        ]
    return [{}]


def _fan_out_key(fan_out: dict[str, str]) -> Optional[str]:
    # Identifies a combination in resume state; none of the values contain the separator.
    return "|".join(fan_out.values()) or None


def _v4_endpoint_config(config: FlutterwaveV4EndpointConfig) -> Endpoint:
    params: dict[str, Any] = {}
    if config.page_size is not None:
        params["size"] = config.page_size

    if config.cursor_data_key is not None:
        return {
            "path": config.path,
            "params": params,
            "data_selector": f"data.{config.cursor_data_key}",
            "paginator": FlutterwaveCursorPaginator(),
        }
    # v4 has no required date window and documents its empty results as an empty `data` array, so
    # neither v3 workaround applies.
    return {
        "path": config.path,
        "params": params,
        "data_selector": "data",
        "paginator": PageNumberPaginator(base_page=1, total_path="meta.page_info.total_pages"),
    }


def _v4_config(endpoint: str) -> FlutterwaveV4EndpointConfig:
    config = FLUTTERWAVE_V4_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"{NOT_ON_V4_ERROR}: {endpoint}")
    return config


def get_rows(
    secret_key: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[FlutterwaveResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    v4_config = _v4_config(endpoint) if api_version == FLUTTERWAVE_API_V4 else None
    client: ClientConfig = {
        "base_url": base_url(api_version),
        "headers": {"Accept": "application/json"},
        "auth": _auth_config(api_version, secret_key, client_id, client_secret),
        # These bodies carry bank account numbers and transaction metadata, so keep them out of
        # the HTTP diagnostic sample store (requests are still metered and logged).
        "session": make_tracked_session(redact_values=_secret_values(secret_key, client_secret), capture=False),
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if v4_config is not None:
        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None:
            if v4_config.cursor_data_key is not None:
                if resume.next_cursor:
                    initial_paginator_state = {"cursor": resume.next_cursor}
            elif resume.next_page > 1:
                initial_paginator_state = {"page": resume.next_page}
        yield from rest_api_resource(
            {"client": client, "resources": [{"name": endpoint, "endpoint": _v4_endpoint_config(v4_config)}]},
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=_checkpoint_hook(resumable_source_manager, None),
            initial_paginator_state=initial_paginator_state,
        )
        return

    fan_out_values = _v3_fan_out_values(endpoint, client, team_id, job_id)
    first_index = 0
    initial_paginator_state = None
    resume_keys = [_fan_out_key(values) for values in fan_out_values]
    if resume is not None and resume.fan_out_value in resume_keys:
        first_index = resume_keys.index(resume.fan_out_value)
        if resume.next_page > 1:
            initial_paginator_state = {"page": resume.next_page}

    for index in range(first_index, len(fan_out_values)):
        fan_out = fan_out_values[index]
        fan_out_key = _fan_out_key(fan_out)
        if index > first_index:
            # Every row of the previous value is yielded, so a hand-off here can start this value
            # from its first page. This also keeps a run of empty values from holding the worker.
            resumable_source_manager.save_state(FlutterwaveResumeConfig(fan_out_value=fan_out_key))
            resumable_source_manager.safe_point()
        resource: EndpointResource = {"name": endpoint, "endpoint": _v3_endpoint_config(endpoint, fan_out)}
        if fan_out:
            resource["data_map"] = _stamp_fields(fan_out)
        yield from rest_api_resource(
            {"client": client, "resources": [resource]},
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=_checkpoint_hook(resumable_source_manager, fan_out_key),
            initial_paginator_state=initial_paginator_state if index == first_index else None,
        )


def _checkpoint_hook(
    resumable_source_manager: ResumableSourceManager[FlutterwaveResumeConfig], fan_out_value: Optional[str]
) -> Callable[[Optional[dict[str, Any]]], None]:
    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls this AFTER a page is yielded and only while a next page remains, so a
        # crash re-yields the next page rather than skipping it (the merge dedupes on primary key).
        if not state:
            return
        if state.get("cursor") is not None:
            resumable_source_manager.save_state(FlutterwaveResumeConfig(next_cursor=str(state["cursor"])))
        elif state.get("page") is not None:
            resumable_source_manager.save_state(
                FlutterwaveResumeConfig(next_page=int(state["page"]), fan_out_value=fan_out_value)
            )

    return save_checkpoint


def _stamp_fields(values: dict[str, str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def stamp(row: dict[str, Any]) -> dict[str, Any]:
        for name, value in values.items():
            row.setdefault(name, value)
        return row

    return stamp


def flutterwave_source(
    secret_key: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[FlutterwaveResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> SourceResponse:
    if api_version == FLUTTERWAVE_API_V4:
        primary_keys = ["id"]
        partition_key = _v4_config(endpoint).partition_key
    else:
        v3_config = FLUTTERWAVE_ENDPOINTS[endpoint]
        primary_keys = v3_config.primary_keys
        partition_key = v3_config.partition_key

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            secret_key=secret_key,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            api_version=api_version,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            client_id=client_id,
            client_secret=client_secret,
        ),
        primary_keys=primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
