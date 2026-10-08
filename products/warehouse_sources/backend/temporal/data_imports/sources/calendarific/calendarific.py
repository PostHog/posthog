import re
from typing import Any

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.calendarific.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    SUBSCRIPTION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calendarific import (
    CalendarificSourceConfig,
)


class CalendarificClient:
    def __init__(self, config: CalendarificSourceConfig, api_version: str) -> None:
        self.config = config
        self.api_version = api_version

    def resource(self, endpoint: str, team_id: int, job_id: str, *, probe: bool = False) -> Resource:
        if endpoint not in ENDPOINTS:
            raise ValueError("Unknown Calendarific table. Select holidays, countries, or languages.")

        params: dict[str, Any] = {}
        if endpoint == "holidays":
            country = self.config.country.strip().upper()
            year = self.config.year.strip()
            if not re.fullmatch(r"[A-Z]{2}", country):
                raise ValueError("Enter a two-letter country code, such as US.")
            if not re.fullmatch(r"[1-9][0-9]{3}", year):
                raise ValueError("Enter a four-digit year, such as 2026.")
            params = {"country": country, "year": year}
            if probe:
                params.update({"month": 1, "day": 1})

        endpoint_config: Endpoint = {
            "path": endpoint,
            "params": params,
            "data_selector": f"response.{endpoint}",
            "data_selector_required": True,
        }
        endpoint_resource: EndpointResource = {
            "name": endpoint,
            "write_disposition": "replace",
            "endpoint": endpoint_config,
        }
        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": f"https://calendarific.com/api/{self.api_version}",
                "auth": {"type": "api_key", "name": "api_key", "api_key": self.config.api_key, "location": "query"},
                "paginator": "single_page",
                "request_timeout": 30,
            },
            "resources": [endpoint_resource],
        }
        return rest_api_resource(rest_config, team_id, job_id, None)

    def validate_credentials(self, team_id: int, schema_name: str | None) -> tuple[bool, str | None]:
        try:
            resource = self.resource(schema_name or "holidays", team_id, "credential-validation", probe=True)
            next(iter(resource), None)
        except ValueError as error:
            return False, str(error)
        except HTTPError as error:
            if error.response is not None:
                if error.response.status_code == 401:
                    return False, AUTH_ERROR
                if error.response.status_code == 403:
                    return False, SUBSCRIPTION_ERROR
            raise
        return True, None

    def source_response(self, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
        resource = self.resource(endpoint, team_id, job_id)
        return SourceResponse(name=endpoint, items=lambda: resource, primary_keys=None, sort_mode=None)
