import json
from http.client import responses
from io import BytesIO
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests import PreparedRequest, Response, Session
from urllib3.response import HTTPResponse

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureapplicationinsights import (
    AzureApplicationInsightsSourceConfig,
)


@pytest.fixture
def config() -> AzureApplicationInsightsSourceConfig:
    return AzureApplicationInsightsSourceConfig(
        tenant_id="00000000-0000-0000-0000-000000000001",
        client_id="00000000-0000-0000-0000-000000000002",
        application_id="00000000-0000-0000-0000-000000000003",
        client_secret="fake-client-secret",
    )


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = False
    return manager


@pytest.fixture
def http_mock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    handler = MagicMock()

    def send(session: Session, request: PreparedRequest, **kwargs: Any) -> Response:
        status, body = handler(request)
        response = Response()
        response.status_code = status
        response.reason = responses[status]
        response.url = request.url or ""
        response.request = request
        response._content = json.dumps(body).encode()
        response.raw = HTTPResponse(body=BytesIO(response._content), preload_content=False)
        response._content_consumed = True  # type: ignore[attr-defined]
        response.headers["Content-Type"] = "application/json"
        return response

    monkeypatch.setattr(Session, "send", send)
    return handler
