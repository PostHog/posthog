import base64
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import Response, Session
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.settings import (
    ACCOUNTS_ENDPOINT,
    BASE_URL,
    ENDPOINTS,
    INITIAL_BACKFILL_DAYS,
    REPORT_INTERVAL,
    TOKEN_URL,
    WINDOW_DAYS,
)

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

    missing_dimensions = sorted(set(endpoint["dimensions"]) - capabilities.dimensions)
    if missing_dimensions:
        raise RoktAdsError(
            f"Rokt account cannot report on {', '.join(missing_dimensions)}, which {endpoint_name} needs "
            f"to identify a row. Deselect this table or ask Rokt to enable those dimensions."
        )

    metrics = [metric for metric in endpoint["metrics"] if metric in capabilities.metrics]
    if not metrics:
        raise RoktAdsError(f"Rokt account grants none of the metrics {endpoint_name} reports on.")

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
            yield rows
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
