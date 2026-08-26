import time
import datetime as dt
from collections.abc import Iterable, Iterator
from dataclasses import field
from typing import Any

import jwt
import requests
import structlog
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.settings import (
    AGGREGATION_PERIOD,
    ERROR_HISTORY_DAYS,
    LIST_ENDPOINTS,
    METRIC_SET_HISTORY_DAYS,
    METRIC_SET_WINDOW_DAYS,
    METRIC_SETS,
    PRIMARY_KEYS,
    ListEndpoint,
    MetricSetEndpoint,
)

logger = structlog.get_logger(__name__)

API_HOST = "https://playdeveloperreporting.googleapis.com"
PLAY_REPORTING_SCOPE = "https://www.googleapis.com/auth/playdeveloperreporting"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"

REQUEST_TIMEOUT_SECONDS = 120
# Google caps service-account assertions (and the tokens minted from them) at one hour.
TOKEN_TTL_SECONDS = 3600
TOKEN_EXPIRY_SKEW_SECONDS = 60

METRIC_PAGE_SIZE = 10000
LIST_PAGE_SIZE = 100
APP_PAGE_SIZE = 50


class GooglePlayConsoleAuthError(Exception):
    """The service account key could not be exchanged for a Play Reporting access token."""


@frozen
class ServiceAccountKey:
    """The fields the source needs out of an uploaded Google service account JSON key."""

    client_email: str
    # Kept out of `repr` so a traceback that prints the key object doesn't carry the PEM.
    private_key: str = field(repr=False)
    private_key_id: str | None = None
    token_uri: str | None = None


@frozen
class GooglePlayConsoleResumeConfig:
    # Package name currently being fetched — apps are walked in sorted order, so anything
    # sorting before this one has already been synced.
    app: str = ""
    # ISO date of the next window to fetch for `app` (metric sets and day-windowed endpoints).
    date: str | None = None
    # Next page token within the current app/day.
    page_token: str | None = None


def _normalize_private_key(private_key: str) -> str:
    """Restore real newlines in a PEM key that arrived with escaped ones.

    Service account JSON stores the key with `\\n` escapes. Parsed JSON has real newlines, but
    a key pasted or round-tripped through a form field often keeps the literal backslash-n,
    which the PEM loader rejects.
    """
    return private_key.replace("\\n", "\n").strip() + "\n"


def _today() -> dt.date:
    return dt.date.today()


def _date_message(value: dt.date) -> dict[str, int]:
    return {"year": value.year, "month": value.month, "day": value.day}


def _date_from_message(message: Any) -> dt.date | None:
    if not isinstance(message, dict):
        return None
    try:
        return dt.date(int(message["year"]), int(message["month"]), int(message["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def _datetime_from_message(message: Any) -> dt.datetime | None:
    """Convert a `google.type.DateTime` body into a naive UTC datetime."""
    day = _date_from_message(message)
    if day is None or not isinstance(message, dict):
        return None
    try:
        return dt.datetime(
            day.year,
            day.month,
            day.day,
            int(message.get("hours") or 0),
            int(message.get("minutes") or 0),
            int(message.get("seconds") or 0),
        )
    except (TypeError, ValueError):
        return None


def _coerce_datetime(value: Any) -> dt.datetime | None:
    """Normalize a Play timestamp to a naive UTC datetime, whichever shape it arrives in.

    The Reporting API returns some timestamps as `google.type.DateTime` objects and others as
    RFC 3339 strings. A column has to hold one type, so unparseable values become null rather
    than leaking a string into a timestamp column.
    """
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dict):
        return _datetime_from_message(value)
    elif isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.UTC).replace(tzinfo=None)
    return parsed


def _dimension_value(dimension: dict[str, Any]) -> Any:
    if "int64Value" in dimension:
        try:
            return int(dimension["int64Value"])
        except (TypeError, ValueError):
            return None
    value = dimension.get("stringValue")
    return value if value is not None else dimension.get("valueLabel")


def _metric_value(metric: dict[str, Any]) -> float | None:
    """Metric values arrive as decimal/int wrappers; keep every metric column a float."""
    raw: Any = None
    decimal = metric.get("decimalValue")
    if isinstance(decimal, dict):
        raw = decimal.get("value")
    elif "int64Value" in metric:
        raw = metric["int64Value"]
    elif "doubleValue" in metric:
        raw = metric["doubleValue"]
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _interval_params(start: dt.datetime, end: dt.datetime) -> dict[str, str]:
    """Query params for a `DateTimeInterval` filter (start inclusive, end exclusive)."""
    params: dict[str, str] = {}
    for prefix, value in (("interval.startTime", start), ("interval.endTime", end)):
        params[f"{prefix}.year"] = str(value.year)
        params[f"{prefix}.month"] = str(value.month)
        params[f"{prefix}.day"] = str(value.day)
        params[f"{prefix}.hours"] = str(value.hour)
        params[f"{prefix}.minutes"] = str(value.minute)
        params[f"{prefix}.seconds"] = str(value.second)
        params[f"{prefix}.timeZone.id"] = "UTC"
    return params


class GooglePlayConsoleClient:
    """Play Developer Reporting client: mints service-account tokens and issues requests."""

    def __init__(self, key: ServiceAccountKey, api_version: str, logger: FilteringBoundLogger) -> None:
        self._client_email = key.client_email
        self._private_key = _normalize_private_key(key.private_key)
        self._private_key_id = key.private_key_id
        # Always mint tokens against Google's fixed endpoint. Never POST to the uploaded key's
        # `token_uri`: a source-write user could point it at an internal host (SSRF) and read back
        # part of the response. Real Google keys always target this URL anyway.
        self._token_uri = DEFAULT_TOKEN_URI
        self._base_url = f"{API_HOST}/{api_version}"
        self._logger = logger
        # Data responses carry customer content (crash stack traces, device details, VCS info) that
        # the name-based sample scrubbers can't recognise, so keep them out of HTTP sample capture.
        self._session = make_tracked_session(redact_values=(self._private_key,), capture=False)
        # The token exchange posts a signed assertion and receives an access token; keep both
        # out of sample capture, where a generic field name wouldn't be scrubbed.
        self._auth_session = make_tracked_session(redact_values=(self._private_key,), capture=False)
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    def _signed_assertion(self, issued_at: int) -> str:
        headers = {"kid": self._private_key_id} if self._private_key_id else None
        try:
            return jwt.encode(
                {
                    "iss": self._client_email,
                    "scope": PLAY_REPORTING_SCOPE,
                    "aud": self._token_uri,
                    "iat": issued_at,
                    "exp": issued_at + TOKEN_TTL_SECONDS,
                },
                self._private_key,
                algorithm="RS256",
                headers=headers,
            )
        except Exception as e:
            raise GooglePlayConsoleAuthError(
                "Could not sign a token with the uploaded service account key. "
                "Please upload the JSON key file Google Cloud generated, unmodified."
            ) from e

    def _mint_access_token(self) -> str:
        issued_at = int(time.time())
        response = self._auth_session.post(
            self._token_uri,
            data={"grant_type": JWT_BEARER_GRANT, "assertion": self._signed_assertion(issued_at)},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise GooglePlayConsoleAuthError(
                f"Google rejected the service account key (status {response.status_code}). "
                "Check that the key is active and the Play Developer Reporting API is enabled "
                f"for its project: {response.text[:200]}"
            )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise GooglePlayConsoleAuthError("Google returned no access token for the service account key")

        try:
            ttl = int(payload.get("expires_in") or TOKEN_TTL_SECONDS)
        except (TypeError, ValueError):
            ttl = TOKEN_TTL_SECONDS
        self._access_token = str(token)
        self._token_expires_at = issued_at + ttl - TOKEN_EXPIRY_SKEW_SECONDS
        return self._access_token

    def _authorization(self) -> str:
        if self._access_token is None or time.time() >= self._token_expires_at:
            return f"Bearer {self._mint_access_token()}"
        return f"Bearer {self._access_token}"

    def _send(
        self, method: str, url: str, params: dict[str, Any] | None, body: dict[str, Any] | None
    ) -> requests.Response:
        return self._session.request(
            method,
            url,
            params=params,
            json=body,
            headers={"Authorization": self._authorization()},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path}"
        response = self._send(method, url, params, body)
        if response.status_code == 401:
            # Access tokens last an hour, so a long sync outlives the one it started with.
            self._access_token = None
            response = self._send(method, url, params, body)

        if not response.ok:
            self._logger.warning(
                "Google Play Console API error",
                status_code=response.status_code,
                url=url,
                body=response.text[:500],
            )
            response.raise_for_status()

        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def list_apps(self) -> list[dict[str, Any]]:
        """Every app the service account can report on."""
        apps: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": APP_PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            payload = self.request("GET", "apps:search", params=params)
            apps.extend(payload.get("apps") or [])
            page_token = payload.get("nextPageToken") or None
            if not page_token:
                return apps

    def latest_available_date(self, package_name: str, resource: str) -> dt.date | None:
        """Last day a metric set has complete data for, per its own freshness report."""
        payload = self.request("GET", f"apps/{package_name}/{resource}")
        freshness_info = payload.get("freshnessInfo") or {}
        for freshness in freshness_info.get("freshnesses") or []:
            if freshness.get("aggregationPeriod") == AGGREGATION_PERIOD:
                # `latestEndTime` is already the exclusive bound Play expects back in
                # `timelineSpec.endTime` (one day past the last day with data), so convert it to an
                # inclusive date here — everything else in this module treats `latest` as inclusive
                # and adds its own `+1 day` when building a query's endTime.
                latest_end = _date_from_message(freshness.get("latestEndTime"))
                return latest_end - dt.timedelta(days=1) if latest_end else None
        return None


def resolve_package_names(client: GooglePlayConsoleClient, requested: Iterable[str]) -> list[str]:
    """Packages to sync: the user's list when given, otherwise everything the account can see.

    Sorted because resume state records the package it stopped on and skips everything before it.
    """
    requested_names = sorted({name for name in requested if name})
    if requested_names:
        return requested_names

    return sorted(
        {package for app in client.list_apps() if (package := app.get("packageName")) is not None},
    )


def parse_package_names(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    separated = raw.replace("\n", ",").replace(" ", ",")
    return tuple(sorted({name.strip() for name in separated.split(",") if name.strip()}))


def _metric_row_to_dict(row: dict[str, Any], package_name: str, endpoint: MetricSetEndpoint) -> dict[str, Any]:
    # Every requested dimension and metric is seeded so the table keeps a stable set of columns
    # even when Play omits one from a row (it drops slices whose user counts fall under its
    # privacy threshold) — the primary key columns in particular must always be there.
    out: dict[str, Any] = {"app": package_name}
    out.update(dict.fromkeys(endpoint.dimensions))
    out.update(dict.fromkeys(endpoint.metrics))

    start_time = row.get("startTime")
    out["date"] = _date_from_message(start_time)
    out["startTime"] = _datetime_from_message(start_time)
    out["endTime"] = _datetime_from_message(row.get("endTime"))

    for dimension in row.get("dimensions") or []:
        name = dimension.get("dimension")
        if not name:
            continue
        out[name] = _dimension_value(dimension)
        label = dimension.get("valueLabel")
        if label is not None:
            out[f"{name}Label"] = label

    for metric in row.get("metrics") or []:
        name = metric.get("metric")
        if not name:
            continue
        out[name] = _metric_value(metric)

    return out


def _query_metric_set(
    client: GooglePlayConsoleClient,
    package_name: str,
    endpoint: MetricSetEndpoint,
    start: dt.date,
    end_inclusive: dt.date,
) -> Iterator[dict[str, Any]]:
    page_token: str | None = None
    while True:
        body: dict[str, Any] = {
            "timelineSpec": {
                "aggregationPeriod": AGGREGATION_PERIOD,
                "startTime": _date_message(start),
                # The timeline's end is exclusive, so ask for the day after the last one wanted.
                "endTime": _date_message(end_inclusive + dt.timedelta(days=1)),
            },
            "dimensions": list(endpoint.dimensions),
            "metrics": list(endpoint.metrics),
            "pageSize": METRIC_PAGE_SIZE,
        }
        if page_token:
            body["pageToken"] = page_token

        payload = client.request("POST", f"apps/{package_name}/{endpoint.resource}:query", body=body)
        yield from payload.get("rows") or []

        page_token = payload.get("nextPageToken") or None
        if not page_token:
            return


def _batch_by_date(rows: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group a window's rows into one batch per day, oldest first.

    A metric-set query can return the days of its window in any order, but the pipeline
    checkpoints the incremental watermark after every batch — so batches have to leave in date
    order, and each has to hold a single day.
    """
    by_date: dict[dt.date, list[dict[str, Any]]] = {}
    undated: list[dict[str, Any]] = []
    for row in rows:
        day = row.get("date")
        if isinstance(day, dt.date):
            by_date.setdefault(day, []).append(row)
        else:
            undated.append(row)

    batches = [by_date[day] for day in sorted(by_date)]
    if undated:
        batches.append(undated)
    return batches


def _iter_metric_set_rows(
    client: GooglePlayConsoleClient,
    endpoint: MetricSetEndpoint,
    package_names: list[str],
    history_start: dt.date,
    manager: ResumableSourceManager[GooglePlayConsoleResumeConfig],
    resume: GooglePlayConsoleResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    resume_app = resume.app if resume and resume.app else None
    resume_date = resume.date if resume else None

    for package_name in package_names:
        if resume_app is not None and package_name < resume_app:
            continue

        window_start = history_start
        if package_name == resume_app and resume_date is not None:
            window_start = _parse_date(resume_date) or history_start
            resume_app = None

        latest = client.latest_available_date(package_name, endpoint.resource)
        if latest is None:
            # No freshness for this metric set means the app has no data we can query for it — a metric
            # set the app isn't eligible for, or one with too little volume to report. Querying a guessed
            # window anyway is rejected with `400 invalid_timeframe`, which failed the whole multi-app
            # sync every run; skip the app so the others still sync.
            continue

        current = window_start
        while current <= latest:
            window_end = min(current + dt.timedelta(days=METRIC_SET_WINDOW_DAYS - 1), latest)
            rows = [
                _metric_row_to_dict(row, package_name, endpoint)
                for row in _query_metric_set(client, package_name, endpoint, current, window_end)
            ]
            yield from _batch_by_date(rows)

            current = window_end + dt.timedelta(days=1)
            manager.save_state(GooglePlayConsoleResumeConfig(app=package_name, date=current.isoformat()))


def _list_row_to_dict(row: dict[str, Any], package_name: str | None, endpoint: ListEndpoint) -> dict[str, Any]:
    out = dict(row)
    if package_name is not None:
        out["app"] = package_name
    for field_name in endpoint.datetime_fields:
        # The cursor column is always emitted, even when absent from the row, so the incremental
        # field never disappears from the table. Other timestamps are only coerced when present,
        # to avoid inventing an all-null column.
        if field_name in out or field_name == endpoint.incremental_field:
            out[field_name] = _coerce_datetime(out.get(field_name))
    return out


def _paginate(
    client: GooglePlayConsoleClient,
    endpoint: ListEndpoint,
    path: str,
    params: dict[str, Any],
    package_name: str | None,
    page_token: str | None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk one collection, yielding each page with the token that follows it."""
    while True:
        page_params: dict[str, Any] = {**params, "pageSize": LIST_PAGE_SIZE}
        if page_token:
            page_params["pageToken"] = page_token

        payload = client.request("GET", path, params=page_params)
        rows = [_list_row_to_dict(row, package_name, endpoint) for row in payload.get(endpoint.data_key) or []]
        next_token = payload.get("nextPageToken") or None
        yield rows, next_token

        if not next_token:
            return
        page_token = next_token


def _iter_list_rows(
    client: GooglePlayConsoleClient,
    endpoint: ListEndpoint,
    package_names: list[str],
    history_start: dt.date,
    manager: ResumableSourceManager[GooglePlayConsoleResumeConfig],
    resume: GooglePlayConsoleResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    if not endpoint.per_app:
        for rows, next_token in _paginate(
            client, endpoint, endpoint.path, {}, None, resume.page_token if resume else None
        ):
            if rows:
                yield rows
            manager.save_state(GooglePlayConsoleResumeConfig(page_token=next_token))
        return

    resume_app = resume.app if resume and resume.app else None
    resume_date = resume.date if resume else None
    resume_token = resume.page_token if resume else None

    for package_name in package_names:
        if resume_app is not None and package_name < resume_app:
            continue

        resuming_this_app = package_name == resume_app
        path = endpoint.path.format(app=package_name)

        if endpoint.interval_mode == "daily":
            start = history_start
            if resuming_this_app and resume_date is not None:
                start = _parse_date(resume_date) or history_start
            page_token = resume_token if resuming_this_app else None

            day = start
            today = _today()
            while day <= today:
                params: dict[str, Any] = _interval_params(
                    dt.datetime.combine(day, dt.time.min),
                    dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min),
                )
                for rows, next_token in _paginate(client, endpoint, path, params, package_name, page_token):
                    if rows:
                        yield rows
                    # A finished day checkpoints the next one, so a restart doesn't re-walk it.
                    manager.save_state(
                        GooglePlayConsoleResumeConfig(
                            app=package_name,
                            date=day.isoformat() if next_token else (day + dt.timedelta(days=1)).isoformat(),
                            page_token=next_token,
                        )
                    )
                page_token = None
                day += dt.timedelta(days=1)
        else:
            trailing_params: dict[str, Any] = {}
            if endpoint.interval_mode == "trailing":
                trailing_params = _interval_params(
                    dt.datetime.combine(history_start, dt.time.min),
                    dt.datetime.combine(_today() + dt.timedelta(days=1), dt.time.min),
                )
            page_token = resume_token if resuming_this_app else None
            for rows, next_token in _paginate(client, endpoint, path, trailing_params, package_name, page_token):
                if rows:
                    yield rows
                manager.save_state(GooglePlayConsoleResumeConfig(app=package_name, page_token=next_token))

        if resuming_this_app:
            resume_app = None
            resume_token = None


def _parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def resolve_history_start(today: dt.date, watermark: Any, history_days: int) -> dt.date:
    """First day to request: the stored watermark, floored at the retained history window."""
    earliest = today - dt.timedelta(days=history_days)
    last_synced = _parse_date(watermark)
    if last_synced is None:
        return earliest
    return max(last_synced, earliest)


def validate_credentials(key: ServiceAccountKey, api_version: str) -> tuple[bool, str | None]:
    """Mint a token and list the apps it can reach."""
    client = GooglePlayConsoleClient(key, api_version, logger)
    try:
        client.list_apps()
    except GooglePlayConsoleAuthError as e:
        return False, str(e)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 401:
            return False, "Google rejected the service account credentials. Please upload a current JSON key."
        if status in (403, 404):
            return (
                False,
                "The service account can't read Play Console reporting data. Enable the Play Developer "
                "Reporting API in its Google Cloud project and invite the service account in Play Console "
                "with permission to view app quality data.",
            )
        return False, f"Could not reach the Play Developer Reporting API: {e}"
    except Exception as e:
        return False, f"Could not reach the Play Developer Reporting API: {e}"

    return True, None


def _load_resume_state(
    manager: ResumableSourceManager[GooglePlayConsoleResumeConfig],
) -> GooglePlayConsoleResumeConfig | None:
    return manager.load_state() if manager.can_resume() else None


def _metric_set_response(
    endpoint: MetricSetEndpoint,
    key: ServiceAccountKey,
    package_names: tuple[str, ...],
    api_version: str,
    manager: ResumableSourceManager[GooglePlayConsoleResumeConfig],
    logger: FilteringBoundLogger,
    watermark: Any,
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, Any]]]:
        client = GooglePlayConsoleClient(key, api_version, logger)
        yield from _iter_metric_set_rows(
            client=client,
            endpoint=endpoint,
            package_names=resolve_package_names(client, package_names),
            history_start=resolve_history_start(_today(), watermark, METRIC_SET_HISTORY_DAYS),
            manager=manager,
            resume=_load_resume_state(manager),
        )

    return SourceResponse(
        name=endpoint.name,
        items=get_rows,
        primary_keys=PRIMARY_KEYS[endpoint.name],
        partition_mode="datetime",
        partition_format="day",
        partition_keys=["date"],
        sort_mode="asc",
    )


def _list_endpoint_response(
    endpoint: ListEndpoint,
    key: ServiceAccountKey,
    package_names: tuple[str, ...],
    api_version: str,
    manager: ResumableSourceManager[GooglePlayConsoleResumeConfig],
    logger: FilteringBoundLogger,
    watermark: Any,
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, Any]]]:
        client = GooglePlayConsoleClient(key, api_version, logger)
        yield from _iter_list_rows(
            client=client,
            endpoint=endpoint,
            package_names=resolve_package_names(client, package_names) if endpoint.per_app else [],
            history_start=resolve_history_start(_today(), watermark, ERROR_HISTORY_DAYS),
            manager=manager,
            resume=_load_resume_state(manager),
        )

    if endpoint.incremental_field is not None:
        return SourceResponse(
            name=endpoint.name,
            items=get_rows,
            primary_keys=PRIMARY_KEYS[endpoint.name],
            partition_mode="datetime",
            partition_format="day",
            partition_keys=[endpoint.incremental_field],
            sort_mode="asc",
        )

    return SourceResponse(
        name=endpoint.name,
        items=get_rows,
        primary_keys=PRIMARY_KEYS[endpoint.name],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def google_play_console_source(
    key: ServiceAccountKey,
    package_names: tuple[str, ...],
    resource_name: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[GooglePlayConsoleResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    watermark = db_incremental_field_last_value if should_use_incremental_field else None

    metric_set = METRIC_SETS.get(resource_name)
    if metric_set is not None:
        return _metric_set_response(
            metric_set, key, package_names, api_version, resumable_source_manager, logger, watermark
        )

    list_endpoint = LIST_ENDPOINTS.get(resource_name)
    if list_endpoint is not None:
        return _list_endpoint_response(
            list_endpoint, key, package_names, api_version, resumable_source_manager, logger, watermark
        )

    raise ValueError(f"Unknown Google Play Console endpoint: {resource_name}")
