import json
from collections.abc import Callable, Iterator
from http import HTTPStatus

import pytest
from unittest.mock import MagicMock, Mock, patch

from django.test import override_settings

import structlog
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.heygen import HeyGenResumeConfig


@pytest.fixture
def response() -> Callable[..., Response]:
    def make_response(body: object, status: int = 200) -> Response:
        result = Response()
        result.status_code = status
        result.reason = HTTPStatus(status).phrase
        result._content = json.dumps(body).encode()
        result.headers["Content-Type"] = "application/json"
        result.url = "https://api.heygen.com/v3/videos"
        return result

    return make_response


@pytest.fixture
def http() -> Iterator[Mock]:
    with patch("requests.Session.send") as send:
        yield send


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="videos",
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-test",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.fixture
def redis() -> Iterator[MagicMock]:
    with (
        override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT=6379),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client"
        ) as get_client,
    ):
        client = get_client.return_value
        client.exists.return_value = 0
        client.get.return_value = None
        yield client


@pytest.fixture
def manager(inputs: SourceInputs, redis: MagicMock) -> ResumableSourceManager[HeyGenResumeConfig]:
    return ResumableSourceManager(inputs, HeyGenResumeConfig)
