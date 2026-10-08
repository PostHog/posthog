import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_application_insights.settings import (
    API_BASE_URL,
    ENDPOINTS,
    LATE_ARRIVAL_OVERLAP,
    PAGE_SIZE,
    SYNC_WINDOW,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureapplicationinsights import (
    AzureApplicationInsightsSourceConfig,
)


@frozen
class AzureApplicationInsightsResumeConfig:
    start: str
    end: str
    timestamp: str | None = None
    item_id: str | None = None


def validate_config(config: AzureApplicationInsightsSourceConfig) -> None:
    for name in ("tenant_id", "client_id", "application_id"):
        try:
            UUID(getattr(config, name))
        except (ValueError, TypeError, AttributeError):
            raise ValueError(f"Enter a valid UUID for {name.replace('_', ' ')}.") from None
    if not config.client_secret.strip():
        raise ValueError("Enter the client secret from your Microsoft Entra app registration.")


def normalize_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("error"):
        raise ValueError("Azure query returned incomplete results. Reduce the telemetry volume and try again.")
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise ValueError("Azure query response has no result table.")
    primary = [table for table in tables if table.get("name") == "PrimaryResult"]
    if len(primary) != 1:
        raise ValueError("Azure query response has no result table.")
    table = primary[0]
    columns = table["columns"]
    names = [column["name"] for column in columns]
    rows = []
    for values in table["rows"]:
        row = dict(zip(names, values, strict=True))
        for column in columns:
            name = column["name"]
            if column["type"] == "dynamic" and isinstance(row[name], str):
                row[name] = json.loads(row[name])
        rows.append(row)
    return rows


class AzureApplicationInsightsClient:
    def __init__(
        self, config: AzureApplicationInsightsSourceConfig, api_version: str, team_id: int, job_id: str
    ) -> None:
        validate_config(config)
        if api_version != "v1":
            raise ValueError("Unsupported Application Insights API version.")
        self.application_id = str(UUID(config.application_id))
        self.api_version = api_version
        self.team_id = team_id
        self.job_id = job_id
        self.auth = OAuth2Auth(
            token_url=f"https://login.microsoftonline.com/{UUID(config.tenant_id)}/oauth2/token",
            client_id=str(UUID(config.client_id)),
            client_secret=config.client_secret,
            extra_token_request_params={"resource": API_BASE_URL},
        )

    def query(self, query: str, timespan: str) -> list[dict[str, Any]]:
        config: RESTAPIConfig = {
            "client": {
                "base_url": API_BASE_URL,
                "auth": self.auth,
                "paginator": "single_page",
                "allowed_hosts": ["api.applicationinsights.io"],
                "allow_redirects": False,
                "request_timeout": (10, 120),
            },
            "resources": [
                {
                    "name": "query",
                    "endpoint": {
                        "path": f"/{self.api_version}/apps/{self.application_id}/query",
                        "method": "POST",
                        "json": {"query": query, "timespan": timespan},
                        "data_selector": "$",
                    },
                    "data_map": normalize_response,
                }
            ],
        }
        return [row for page in rest_api_resource(config, self.team_id, self.job_id, None) for row in page]

    def read_rows(
        self,
        endpoint: str,
        manager: ResumableSourceManager[AzureApplicationInsightsResumeConfig],
        last_value: datetime | str | None,
    ) -> Iterator[list[dict[str, Any]]]:
        if endpoint not in ENDPOINTS:
            raise ValueError("Unknown Application Insights table.")
        state = manager.load_state() if manager.can_resume() else None
        if state is None:
            end = datetime.now(UTC)
            start = end - SYNC_WINDOW
            if last_value is not None:
                watermark = datetime.fromisoformat(last_value) if isinstance(last_value, str) else last_value
                watermark = watermark.replace(tzinfo=UTC) if watermark.tzinfo is None else watermark.astimezone(UTC)
                start = max(start, watermark - LATE_ARRIVAL_OVERLAP)
            state = AzureApplicationInsightsResumeConfig(start=start.isoformat(), end=end.isoformat())
        while True:
            # String literals preserve Azure's sub-microsecond timestamps across page boundaries.
            query = (
                f"{endpoint} | where timestamp >= todatetime({json.dumps(state.start)})"
                f" and timestamp < todatetime({json.dumps(state.end)})"
            )
            if state.timestamp is not None:
                timestamp = f"todatetime({json.dumps(state.timestamp)})"
                query += (
                    f" | where timestamp > {timestamp} or (timestamp == {timestamp}"
                    f" and strcmp(tostring(itemId), {json.dumps(state.item_id)}) > 0)"
                )
            query += f" | order by timestamp asc, itemId asc | take {PAGE_SIZE}"
            rows = self.query(query, f"{state.start}/{state.end}")
            if not rows:
                manager.safe_point()
                return
            for row in rows:
                if (
                    not isinstance(row.get("timestamp"), str)
                    or not isinstance(row.get("itemId"), str)
                    or not row["itemId"]
                ):
                    raise ValueError("Azure telemetry is missing its timestamp or item ID.")
            last = rows[-1]
            if (last["timestamp"], last["itemId"]) == (state.timestamp, state.item_id):
                raise ValueError("Azure query pagination did not advance.")
            state = AzureApplicationInsightsResumeConfig(
                start=state.start, end=state.end, timestamp=last["timestamp"], item_id=last["itemId"]
            )
            manager.save_state(state)
            yield rows
            manager.safe_point()
            if len(rows) < PAGE_SIZE:
                return


def azure_application_insights_source(
    config: AzureApplicationInsightsSourceConfig,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[AzureApplicationInsightsResumeConfig],
    last_value: datetime | str | None,
) -> SourceResponse:
    client = AzureApplicationInsightsClient(config, api_version, team_id, job_id)
    return SourceResponse(
        name=endpoint,
        items=lambda: client.read_rows(endpoint, manager, last_value),
        primary_keys=["itemId"],
        sort_mode="asc",
    )
