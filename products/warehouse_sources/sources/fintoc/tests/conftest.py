import json
from http.client import responses
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests import PreparedRequest, Response, Session


@pytest.fixture
def http_mock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    handler = MagicMock()

    def send(session: Session, request: PreparedRequest, **kwargs: Any) -> Response:
        status, body, headers = handler(request)
        response = Response()
        response.status_code = status
        response.reason = responses[status]
        response.url = request.url or ""
        response.request = request
        response._content = json.dumps(body).encode() if body is not None else b""
        response.headers.update({"Content-Type": "application/json", **headers})
        return response

    monkeypatch.setattr(Session, "send", send)
    monkeypatch.setattr("time.sleep", lambda _: None)
    return handler


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock()
    result.can_resume.return_value = False
    namespaces: dict[str, MagicMock] = {}

    def namespace(key: str) -> MagicMock:
        if key not in namespaces:
            child = MagicMock()
            child.can_resume.return_value = False
            namespaces[key] = child
        return namespaces[key]

    result.with_namespace.side_effect = namespace
    return result


@pytest.fixture
def inputs() -> MagicMock:
    return MagicMock(team_id=1, job_id="fintoc-test-job", schema_name="links", api_version=None)
