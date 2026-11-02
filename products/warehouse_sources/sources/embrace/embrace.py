import json
import math
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.embrace.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    MAX_SYNC_SECONDS,
    PRIMARY_KEYS,
    REGION_HOSTS,
    STEP_SECONDS,
    WINDOW_SECONDS,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.embrace import (
        EmbraceSourceConfig,
    )


@frozen
class EmbraceResumeConfig:
    start: int
    end: int


class MetricRow(TypedDict):
    series_id: str
    timestamp: datetime
    value: float | None
    labels: dict[str, str]


class EmbraceClient:
    def __init__(self, config: "EmbraceSourceConfig", team_id: int, job_id: str, api_version: str) -> None:
        if config.region not in REGION_HOSTS:
            raise ValueError("Invalid Embrace region. Select a region from the list.")
        if not config.app_id.strip():
            raise ValueError("Enter your Embrace app ID.")
        if api_version != "v1":
            raise ValueError("Unsupported Embrace API version. Select v1.")
        self.config = config
        self.team_id = team_id
        self.job_id = job_id
        self.api_version = api_version

    def query(self, endpoint: str, start: int, end: int) -> list[MetricRow]:
        if endpoint not in ENDPOINTS:
            raise ValueError("Unknown Embrace table. Select a supported table.")
        query = ENDPOINTS[endpoint] + "{app_id=" + json.dumps(self.config.app_id) + "}"
        config: RESTAPIConfig = {
            "client": {
                "base_url": f"https://{REGION_HOSTS[self.config.region]}/metrics/api/{self.api_version}/",
                "auth": {"type": "bearer", "token": self.config.api_token},
                "paginator": "single_page",
                "allowed_hosts": [],
                "allow_redirects": False,
                "request_timeout": (10, 60),
            },
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": "query_range",
                        "data_selector": "$",
                        "params": {"query": query, "start": start, "end": end, "step": STEP_SECONDS},
                    },
                }
            ],
        }
        rows: list[MetricRow] = []
        for page in rest_api_resource(config, self.team_id, self.job_id, None):
            for envelope in page:
                if envelope.get("status") != "success" or envelope.get("warnings"):
                    raise ValueError(
                        "Embrace returned an incomplete metrics query. Retry the sync or contact Embrace support."
                    )
                data = envelope["data"]
                if data["resultType"] != "matrix":
                    raise ValueError("Embrace returned an unexpected metrics format. Contact Embrace support.")
                for series in data["result"]:
                    labels = series["metric"]
                    series_id = hashlib.sha256(
                        json.dumps(labels, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                    for timestamp, raw_value in series["values"]:
                        value = float(raw_value)
                        rows.append(
                            MetricRow(
                                series_id=series_id,
                                timestamp=datetime.fromtimestamp(float(timestamp), tz=UTC),
                                value=value if math.isfinite(value) else None,
                                labels=labels,
                            )
                        )
        return sorted(rows, key=lambda row: row["timestamp"], reverse=True)


def validate_credentials(
    config: "EmbraceSourceConfig", team_id: int, endpoint: str, api_version: str
) -> tuple[bool, str | None]:
    try:
        client = EmbraceClient(config, team_id, "", api_version)
        timestamp = int(datetime.now(UTC).timestamp()) // STEP_SECONDS * STEP_SECONDS - STEP_SECONDS
        client.query(endpoint, timestamp, timestamp)
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status is not None and status in AUTH_ERRORS:
            return False, AUTH_ERRORS[status]
        raise
    except ValueError as error:
        return False, str(error)
    return True, None


def embrace_source(
    config: "EmbraceSourceConfig",
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: "ResumableSourceManager[EmbraceResumeConfig]",
    last_value: datetime | str | None,
    api_version: str,
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError("Unknown Embrace table. Select a supported table.")
    client = EmbraceClient(config, team_id, job_id, api_version)

    def get_rows() -> Iterator[list[MetricRow]]:
        end = int(datetime.now(UTC).timestamp()) // STEP_SECONDS * STEP_SECONDS - STEP_SECONDS
        start = end - MAX_SYNC_SECONDS + STEP_SECONDS
        if last_value is not None:
            watermark = datetime.fromisoformat(last_value) if isinstance(last_value, str) else last_value
            watermark = watermark.replace(tzinfo=UTC) if watermark.tzinfo is None else watermark
            start = max(start, int(watermark.timestamp()) // STEP_SECONDS * STEP_SECONDS - STEP_SECONDS)
        state = manager.load_state() if manager.can_resume() else None
        if state is not None:
            start = state.start
            end = state.end
        while end >= start:
            window_start = max(start, end - WINDOW_SECONDS + STEP_SECONDS)
            rows = client.query(endpoint, window_start, end)
            manager.save_state(EmbraceResumeConfig(start=start, end=window_start - STEP_SECONDS))
            if rows:
                yield rows
            manager.safe_point()
            end = window_start - STEP_SECONDS

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=PRIMARY_KEYS,
        partition_keys=["timestamp"],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
