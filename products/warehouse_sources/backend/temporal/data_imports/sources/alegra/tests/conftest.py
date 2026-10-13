import json
from collections.abc import Callable
from typing import Any

import pytest

import structlog
from requests import PreparedRequest, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alegra import AlegraSourceConfig


@pytest.fixture
def config() -> AlegraSourceConfig:
    return AlegraSourceConfig(email="warehouse@example.com", api_token="fake-alegra-token")


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="invoices",
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2025-01-01",
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-test",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.fixture
def http_boundary(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[PreparedRequest]]:
    def install(responses: list[tuple[int, Any]], headers: dict[str, str] | None = None) -> list[PreparedRequest]:
        requests: list[PreparedRequest] = []
        queued = iter(responses)

        def send(session: Session, request: PreparedRequest, **kwargs: Any) -> Response:
            requests.append(request)
            status, body = next(queued)
            response = Response()
            response.status_code = status
            response.reason = {401: "Unauthorized", 403: "Forbidden", 400: "Bad Request"}.get(status, "OK")
            response.url = request.url or ""
            response.request = request
            response._content = json.dumps(body).encode()
            response.headers.update(headers or {})
            return response

        monkeypatch.setattr(Session, "send", send)
        return requests

    return install


@pytest.fixture
def redis_boundary(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    saved: dict[str, str] = {}

    class MemoryRedis:
        def ping(self) -> bool:
            return True

        def exists(self, key: str) -> int:
            return int(key in saved)

        def get(self, key: str) -> str | None:
            return saved.get(key)

        def set(self, key: str, value: str, ex: int) -> None:
            saved[key] = value

    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
        lambda url: MemoryRedis(),
    )
    return saved
