import time
from collections.abc import Iterator
from dataclasses import field, replace
from typing import Any
from urllib.parse import quote, urlsplit

from requests import PreparedRequest, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    APIKeyAuth,
    BearerTokenAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.umami import UmamiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.umami.settings import (
    DAY_MS,
    DEFAULT_BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)

REQUEST_TIMEOUT = (10, 30)
# A server-supplied date range outside this span is implausible. Rejecting it bounds the number of event windows.
MIN_TIMESTAMP_MS = 631_152_000_000  # 1990-01-01
MAX_FUTURE_MS = 366 * DAY_MS


class UmamiError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(f"Umami configuration: {message}")


@frozen
class UmamiResumeState:
    page: int = 1
    completed_websites: list[str] = field(default_factory=list)
    website_id: str | None = None
    start_at: int | None = None
    end_at: int | None = None
    stop_at: int | None = None


def normalize_host(host: str | None) -> str:
    base_url = (host or DEFAULT_BASE_URL).strip().rstrip("/")
    if "://" not in base_url:
        base_url = f"https://{base_url}"
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise UmamiError("Enter an HTTPS API URL without credentials, a query, or a fragment.")
    if parsed.hostname == "api.umami.is":
        if parsed.path not in ("/v1", "/v1/us", "/v1/eu"):
            raise UmamiError("Use https://api.umami.is/v1, /v1/us, or /v1/eu for Umami Cloud.")
    elif not parsed.path.endswith("/api"):
        base_url += "/api"
    return base_url


def timestamp_ms(value: object) -> int:
    try:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return int(value)
        parsed = parse_datetime_value(value)
        if parsed is not None:
            return int(parsed.timestamp() * 1000)
    except (OverflowError, ValueError, OSError):
        pass
    raise UmamiError("Umami returned an invalid date range. Check the server API version.")


class UmamiClient:
    def __init__(self, config: UmamiSourceConfig) -> None:
        self.base_url = normalize_host(config.host)
        self.cloud = urlsplit(self.base_url).hostname == "api.umami.is"
        self.username = config.username or ""
        key = config.api_key or ""
        self.password = (config.password or "") if not key else ""
        if not key and (self.cloud or not self.username or not self.password):
            raise UmamiError("Enter an API key, or a self-hosted username and password.")
        self.session = make_tracked_session(redact_values=(key, self.password), allow_redirects=False, capture=False)
        self.auth: APIKeyAuth | BearerTokenAuth = (
            APIKeyAuth(api_key=key, name="x-umami-api-key") if self.cloud else BearerTokenAuth(token=key)
        )
        if self.cloud:
            self.session.hooks["response"].append(self._pace)
        if not key:
            self.session.hooks["response"].append(self._refresh)

    def __enter__(self) -> "UmamiClient":
        try:
            if self.password:
                self._login()
        except Exception:
            self.session.close()
            raise
        return self

    def __exit__(self, *args: object) -> None:
        self.session.close()

    @staticmethod
    def _pace(response: Response, **kwargs: Any) -> Response:
        # Space requests below the Cloud quota. Transport retries still honor Retry-After.
        interruptible_wait(0.35)
        return response

    def _login(self) -> None:
        response = self.session.post(
            f"{self.base_url}/auth/login",
            json={"username": self.username, "password": self.password},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("requiresTwoFactor"):
            raise UmamiError("Use an API key for an account with two-factor authentication.")
        token = body.get("token")
        if not isinstance(token, str) or not token:
            raise UmamiError("Umami did not return a login token. Check the server API version.")
        assert isinstance(self.auth, BearerTokenAuth)
        self.auth.token = token

    def _refresh(self, response: Response, **kwargs: Any) -> Response:
        if response.status_code != 401 or response.request.url == f"{self.base_url}/auth/login":
            return response
        response.close()
        self._login()
        request: PreparedRequest = response.request.copy()
        self.auth(request)
        # Replay once without this hook so rejected credentials cannot cause an endless login loop.
        request.hooks["response"] = []
        return self.session.send(request, **kwargs)

    def client_config(self) -> ClientConfig:
        return {
            "base_url": self.base_url,
            "auth": self.auth,
            "session": self.session,
            "request_timeout": REQUEST_TIMEOUT,
            "allowed_hosts": [],
            "allow_redirects": False,
        }

    def resource(
        self,
        name: str,
        inputs: SourceInputs,
        *,
        path: str | None = None,
        params: dict[str, Any] | None = None,
        page: int = 1,
    ) -> Resource:
        endpoint: Endpoint = {
            "path": path or ENDPOINTS[name].path,
            "data_selector": "data",
            "data_selector_required": True,
            "params": {"pageSize": PAGE_SIZE, **(params or {})},
            "paginator": PageNumberPaginator(base_page=1, page=page),
            "response_actions": [
                {
                    "status_code": 200,
                    "json_field": "isCapped",
                    "json_values": [True],
                    "action": "raise",
                    "message": "Umami configuration: Umami capped the results. Increase the API result limit before syncing.",
                }
            ],
        }
        config: RESTAPIConfig = {
            "client": self.client_config(),
            "resources": [{"name": name, "endpoint": endpoint, "write_disposition": "replace"}],
        }
        return rest_api_resource(config, inputs.team_id, inputs.job_id, None)

    def probe(self) -> None:
        params: dict[str, str | int] = {"page": 1, "pageSize": 1, "includeTeams": "true"}
        response = self.session.get(
            f"{self.base_url}/websites",
            params=params,
            auth=self.auth,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        if not isinstance(response.json().get("data"), list):
            raise UmamiError("Umami did not return a website list. Check the API URL.")

    def date_range(self, website_id: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/websites/{quote(website_id, safe='')}/daterange",
            auth=self.auth,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()


def get_rows(
    config: UmamiSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[UmamiResumeState],
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    state = state or UmamiResumeState()
    with UmamiClient(config) as client:
        manager.safe_point()
        websites = client.resource(
            "websites",
            inputs,
            params={"includeTeams": "true"},
            page=state.page if inputs.schema_name == "websites" else 1,
        )
        if inputs.schema_name == "websites":
            page_number = state.page
            for batch in websites:
                page_number += 1
                manager.save_state(UmamiResumeState(page=page_number))
                yield batch
                manager.safe_point()
            manager.safe_point()
            return

        # Each website has its own date range, so each window needs a separately configured resource.
        endpoint = ENDPOINTS[inputs.schema_name]
        for website_batch in websites:
            manager.safe_point()
            for website in website_batch:
                manager.save_state(state)
                manager.safe_point()
                website_id = str(website["id"])
                if website_id in state.completed_websites:
                    continue
                if state.website_id != website_id:
                    dates = client.date_range(website_id)
                    manager.safe_point()
                    if "startDate" not in dates or "endDate" not in dates:
                        raise UmamiError("Umami returned an invalid date range. Check the server API version.")
                    if dates["startDate"] is None or dates["endDate"] is None:
                        state = replace(state, completed_websites=[*state.completed_websites, website_id])
                        manager.save_state(state)
                        manager.safe_point()
                        continue
                    start_at = timestamp_ms(dates.get("startDate"))
                    stop_at = timestamp_ms(dates.get("endDate"))
                    if start_at > stop_at:
                        raise UmamiError("Umami returned a reversed date range. Check the server API version.")
                    if start_at < MIN_TIMESTAMP_MS or stop_at > int(time.time() * 1000) + MAX_FUTURE_MS:
                        raise UmamiError("Umami returned an implausible date range. Check the server API version.")
                    state = replace(
                        state, website_id=website_id, start_at=start_at, stop_at=stop_at, end_at=None, page=1
                    )

                assert state.start_at is not None and state.stop_at is not None
                while state.start_at <= state.stop_at:
                    end_at = (
                        state.end_at
                        if state.end_at is not None
                        else (
                            min(state.start_at + endpoint.window_size_ms - 1, state.stop_at)
                            if endpoint.window_size_ms
                            else state.stop_at
                        )
                    )
                    state = replace(state, end_at=end_at)
                    manager.save_state(state)
                    manager.safe_point()
                    resource = client.resource(
                        inputs.schema_name,
                        inputs,
                        path=endpoint.path.format(website_id=quote(website_id, safe="")),
                        params={"startAt": state.start_at, "endAt": end_at},
                        page=state.page,
                    )
                    for batch in resource:
                        for row in batch:
                            row["websiteId"] = website_id
                        state = replace(state, page=state.page + 1)
                        manager.save_state(state)
                        yield batch
                        manager.safe_point()
                    state = replace(state, start_at=end_at + 1, end_at=None, page=1)
                state = UmamiResumeState(completed_websites=[*state.completed_websites, website_id])
        manager.save_state(state)
        manager.safe_point()


def umami_source(
    config: UmamiSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[UmamiResumeState],
) -> SourceResponse:
    endpoint = ENDPOINTS[inputs.schema_name]
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: get_rows(config, inputs, manager),
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        # Windows and websites have no global timestamp order. Full refresh needs no watermark.
        sort_mode=None,
        on_complete=manager.clear_state,
    )
