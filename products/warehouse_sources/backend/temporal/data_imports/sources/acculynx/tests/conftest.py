import json
from collections.abc import Callable, Iterator
from http import HTTPStatus
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

import fakeredis
from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.acculynx import AcculynxResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.source import AcculynxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common import resumable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.acculynx import (
    AcculynxSourceConfig,
)


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="contacts",
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2099-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-test",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch, inputs: SourceInputs) -> ResumableSourceManager[AcculynxResumeConfig]:
    redis = fakeredis.FakeRedis()
    monkeypatch.setattr(resumable, "get_client", lambda _: redis)
    monkeypatch.setattr(settings, "DATA_WAREHOUSE_REDIS_HOST", "localhost")
    monkeypatch.setattr(settings, "DATA_WAREHOUSE_REDIS_PORT", 6379)
    return AcculynxSource().get_resumable_source_manager(inputs)


@pytest.fixture
def http_send() -> Iterator[MagicMock]:
    with patch("requests.sessions.Session.send") as send:
        yield send


@pytest.fixture
def response() -> Callable[..., Response]:
    def build(request: PreparedRequest, body: Any, status: int = 200) -> Response:
        result = Response()
        result.status_code = status
        result.reason = HTTPStatus(status).phrase
        result.url = request.url
        result.request = request
        result._content = json.dumps(body).encode()
        result.headers["Content-Type"] = "application/json"
        return result

    return build


@pytest.fixture
def pipeline(
    inputs: SourceInputs, manager: ResumableSourceManager[AcculynxResumeConfig]
) -> Callable[..., SourceResponse]:
    def build(name: str, **fields: str) -> SourceResponse:
        inputs.schema_name = name
        config = AcculynxSourceConfig.from_dict({"api_key": "fake-acculynx-key", **fields})
        return AcculynxSource().source_for_pipeline(config, manager, inputs)

    return build
