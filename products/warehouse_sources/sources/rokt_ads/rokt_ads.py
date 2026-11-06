import base64
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

from requests import Response, Session
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.rokt_ads.settings import (
    ACCOUNTS_ENDPOINT,
    BASE_URL,
    DISCOVERY_METRICS,
    ENDPOINTS,
    INITIAL_BACKFILL_DAYS,
    METADATA_ENDPOINTS,
    REPORT_INTERVAL,
    TOKEN_URL,
    WINDOW_DAYS,
)
from products.warehouse_sources.sources.sdk import ResumableSourceManager, frozen, make_tracked_session

# Rokt access tokens last an hour. Refresh early so a long window request cannot start on a token
# that expires mid-flight.
TOKEN_EXPIRY_MARGIN_SECONDS = 300


@frozen
class RoktAdsResumeConfig:
    next_start_date: str


@frozen
class ReportCapabilities:
    dimensions: set[str]
    metrics: set[str]


@frozen
class DateWindow:
    start: date
    end: date


class RoktAdsError(Exception):
    pass


def _error_detail(response: Response) -> str:
    """Pull Rokt's explanation of a rejected request out of the error body.

    Rokt does not document its error shape, so read the keys it is likely to use and fall
    back to the raw text. Without this the caller keeps only the bare status line and loses
    the reason Rokt refused the request.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:500]

    if isinstance(body, dict):
        detail = body.get("message") or body.get("error") or body.get("detail") or body.get("errors")
        if detail:
            return str(detail)[:500]
    if isinstance(body, list) and body:
        return str(body[0])[:500]
    return str(body)[:500]


class RoktAdsClient:
    """Talks to the Rokt Query API and keeps the client-credentials token fresh."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        session: Optional[Session] = None,
        token_session: Optional[Session] = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._session = session or make_tracked_session(redact_values=(app_id, app_secret))
        # The token exchange sends the secret inside a base64 Basic header, which no literal-value
        # denylist can mask, so that one call stays out of sample capture entirely.
        self._token_session = token_session or make_tracked_session(redact_values=(app_id, app_secret), capture=False)
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    def _basic_auth_header(self) -> str:
        encoded = base64.b64encode(f"{self._app_id}:{self._app_secret}".encode("ascii")).decode("ascii")
        return f"Basic {encoded}"

    def _token_is_fresh(self) -> bool:
        if self._token is None or self._token_expires_at is None:
            return False
        return datetime.now(tz=UTC) < self._token_expires_at

    def access_token(self) -> str:
        if self._token_is_fresh():
            assert self._token is not None
            return self._token

        response = self._token_session.post(
            TOKEN_URL,
            headers={
                "Authorization": self._basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
        )
        response.raise_for_status()
        payload = response.json()

        token = payload.get("access_token")
        if not token:
            raise RoktAdsError("Rokt token response contained no access_token")

        expires_in = int(payload.get("expires_in", 3600))
        self._token = token
        self._token_expires_at = datetime.now(tz=UTC) + timedelta(
            seconds=max(expires_in - TOKEN_EXPIRY_MARGIN_SECONDS, 0)
        )
        return token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token()}", "Content-Type": "application/json"}

    @staticmethod
    def _raise_for_status(response: Response) -> None:
        """Turn an error response into a `RoktAdsError` that carries Rokt's own explanation.

        The status line stays in the message, so `get_non_retryable_errors` keeps matching it.
        """
        try:
            response.raise_for_status()
        except HTTPError as err:
            detail = _error_detail(response)
            raise RoktAdsError(f"{err} — {detail}" if detail else str(err)) from err

    def get(self, path: str) -> Any:
        response = self._session.get(f"{BASE_URL}{path}", headers=self._auth_headers())
        self._raise_for_status(response)
        return response.json()

    def post(self, path: str, body: dict[str, Any]) -> Any:
        response = self._session.post(f"{BASE_URL}{path}", headers=self._auth_headers(), json=body)
        self._raise_for_status(response)
        return response.json()

    def get_metadata(self, path: str) -> Optional[dict[str, Any]]:
        """Read one metadata object, or None when Rokt no longer has it."""
        try:
            payload = self.get(path)
        except RoktAdsError as err:
            # An ID from an old report can point at a campaign, creative or audience Rokt has since
            # removed. Skip it, because the shared 404 rule would otherwise fail the whole sync.
            cause = err.__cause__
            if isinstance(cause, HTTPError) and cause.response is not None and cause.response.status_code == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def list_accounts(self) -> list[dict[str, Any]]:
        payload = self.get("/v1/query/accounts")
        return payload if isinstance(payload, list) else []

    def report_capabilities(self, account_id: str, kind: str) -> ReportCapabilities:
        """Dimension and metric slugs this account may request for a report resource."""
        payload = self.get(f"/v1/query/accounts/{account_id}/{kind}/help")
        return ReportCapabilities(
            dimensions={item["slug"] for item in payload.get("dimensions", []) if item.get("slug")},
            metrics={item["slug"] for item in payload.get("metrics", []) if item.get("slug")},
        )

    def run_report(self, account_id: str, kind: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        path = f"/v1/query/accounts/{account_id}/campaigns/"
        if kind == "transactions":
            path = f"/v1/query/accounts/{account_id}/transactions"
        payload = self.post(path, body)
        data = payload.get("data")
        return data if isinstance(data, list) else []


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Report cursors come back as ISO timestamps; Rokt's date params take the date half.
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def _date_windows(start: date, end: date, window_days: int) -> Iterator[DateWindow]:
    """Split [start, end) into consecutive half-open windows, oldest first."""
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=window_days), end)
        yield DateWindow(start=cursor, end=window_end)
        cursor = window_end


def resolve_start_date(db_incremental_field_last_value: Optional[Any], today: date) -> date:
    cursor = _as_date(db_incremental_field_last_value)
    if cursor is None:
        return today - timedelta(days=INITIAL_BACKFILL_DAYS)
    return cursor


def _require_dimensions(endpoint_name: str, dimensions: list[str], capabilities: ReportCapabilities) -> None:
    missing_dimensions = sorted(set(dimensions) - capabilities.dimensions)
    if missing_dimensions:
        raise RoktAdsError(
            f"Rokt account cannot report on {', '.join(missing_dimensions)}, which {endpoint_name} needs "
            f"to identify a row. Deselect this table or ask Rokt to enable those dimensions."
        )


def _granted_metrics(endpoint_name: str, metrics: list[str], capabilities: ReportCapabilities) -> list[str]:
    granted = [metric for metric in metrics if metric in capabilities.metrics]
    if not granted:
        raise RoktAdsError(f"Rokt account grants none of the metrics {endpoint_name} reports on.")
    return granted


def build_discovery_body(endpoint_name: str, window: DateWindow, capabilities: ReportCapabilities) -> dict[str, Any]:
    """Ask for one row per distinct ID tuple in the window. No `interval`, so days do not multiply rows."""
    endpoint = METADATA_ENDPOINTS[endpoint_name]
    _require_dimensions(endpoint_name, endpoint["discovery_dimensions"], capabilities)
    metrics = _granted_metrics(endpoint_name, DISCOVERY_METRICS, capabilities)
    return {
        "startDate": window.start.isoformat(),
        "endDate": window.end.isoformat(),
        "metrics": metrics[:1],
        "dimensions": endpoint["discovery_dimensions"],
    }


def _id_tuple(row: dict[str, Any], dimensions: list[str]) -> Optional[tuple[str, ...]]:
    values = [row.get(dimension) for dimension in dimensions]
    if any(value is None or str(value).strip() == "" for value in values):
        return None
    return tuple(str(value) for value in values)


def rokt_ads_metadata_rows(
    client: RoktAdsClient,
    account_id: str,
    endpoint_name: str,
    resumable_source_manager: ResumableSourceManager[RoktAdsResumeConfig],
    today: Optional[date] = None,
) -> Iterator[dict[str, Any]]:
    """Discover IDs window by window over the backfill range, then read each new ID's metadata once.

    A full refresh: the set of IDs comes from performance reports, so there is no server-side
    timestamp to filter metadata on. One row is yielded per metadata request, and a safe point
    follows each request that yields nothing.
    """
    endpoint = METADATA_ENDPOINTS[endpoint_name]
    capabilities = client.report_capabilities(account_id, "campaigns")

    current_day = today or datetime.now(tz=UTC).date()
    start_date = current_day - timedelta(days=INITIAL_BACKFILL_DAYS)
    end_date = current_day + timedelta(days=1)

    seen: set[tuple[str, ...]] = set()
    for window in _date_windows(start_date, end_date, WINDOW_DAYS):
        body = build_discovery_body(endpoint_name, window, capabilities)
        report_rows = client.run_report(account_id, "campaigns", body)
        resumable_source_manager.safe_point()

        for report_row in report_rows:
            ids = _id_tuple(report_row, endpoint["discovery_dimensions"])
            if ids is None or ids in seen:
                continue
            seen.add(ids)

            path = endpoint["path"].format(
                *(quote(value, safe="") for value in ids), account_id=quote(account_id, safe="")
            )
            metadata = client.get_metadata(path)
            if metadata is None:
                resumable_source_manager.safe_point()
                continue
            # The path IDs win, so the primary key is always set even if Rokt omits a field.
            yield {**metadata, **dict(zip(endpoint["id_fields"], ids))}


def build_report_body(
    endpoint_name: str,
    window: DateWindow,
    capabilities: ReportCapabilities,
    timezone_variation: Optional[str],
    currency_code: Optional[str],
) -> dict[str, Any]:
    """Assemble one report request, narrowed to what the account may actually ask for.

    Metrics are intersected with the account's capabilities: losing one drops a column. Dimensions
    are not, because they set the row grain — dropping one would silently collapse rows onto a
    primary key that no longer identifies them.
    """
    endpoint = ENDPOINTS[endpoint_name]
    _require_dimensions(endpoint_name, endpoint["dimensions"], capabilities)
    metrics = _granted_metrics(endpoint_name, endpoint["metrics"], capabilities)

    # No `orderBys`: the Query API only sorts on a requested dimension or metric slug, and
    # `datetime` is a response-only interval marker rather than a slug, so ordering by it makes
    # Rokt reject the whole report with a 400. Row order does not matter here anyway - the
    # incremental cursor takes the max `datetime` over each window and resume is window-based.
    body: dict[str, Any] = {
        "interval": REPORT_INTERVAL,
        "startDate": window.start.isoformat(),
        "endDate": window.end.isoformat(),
        "metrics": metrics,
        "dimensions": endpoint["dimensions"],
    }
    if timezone_variation:
        body["timezoneVariation"] = timezone_variation
    if currency_code:
        body["currencyCode"] = currency_code
    return body


def rokt_ads_source(
    client: RoktAdsClient,
    account_id: str,
    endpoint_name: str,
    resumable_source_manager: ResumableSourceManager[RoktAdsResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    timezone_variation: Optional[str] = None,
    currency_code: Optional[str] = None,
    today: Optional[date] = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint_name == ACCOUNTS_ENDPOINT:
        yield client.list_accounts()
        return

    endpoint = ENDPOINTS[endpoint_name]
    capabilities = client.report_capabilities(account_id, endpoint["kind"])

    current_day = today or datetime.now(tz=UTC).date()
    # `endDate` is exclusive, so reaching tomorrow is what includes today.
    end_date = current_day + timedelta(days=1)

    start_date = resolve_start_date(db_incremental_field_last_value, current_day)
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            resumed = _as_date(resume_config.next_start_date)
            if resumed is not None:
                start_date = resumed

    for window in _date_windows(start_date, end_date, WINDOW_DAYS):
        body = build_report_body(endpoint_name, window, capabilities, timezone_variation, currency_code)
        rows = client.run_report(account_id, endpoint["kind"], body)
        if rows:
            yield [{**row, "currency_code": currency_code or "USD"} for row in rows]
        # Saved after the yield: a crash re-reads this window and the merge dedupes on the
        # primary key, where saving first would skip it.
        resumable_source_manager.save_state(RoktAdsResumeConfig(next_start_date=window.end.isoformat()))


def validate_credentials(app_id: str, app_secret: str, account_id: str) -> tuple[bool, str | None]:
    client = RoktAdsClient(app_id, app_secret)
    try:
        client.access_token()
    except Exception:
        return False, "Rokt rejected the app ID or app secret. Please check both and try again."

    try:
        client.get(f"/v1/query/accounts/{account_id}")
    except Exception:
        return False, f"Rokt account {account_id} is not readable with these credentials."

    return True, None
