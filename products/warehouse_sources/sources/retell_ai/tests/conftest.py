import json
from collections.abc import Iterator
from http import HTTPStatus

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import structlog
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.types import IncrementalFieldType


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="calls",
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field="start_timestamp",
        incremental_field_type=IncrementalFieldType.DateTime,
        job_id="test-job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.fixture
def http() -> Iterator[MagicMock]:
    with patch("requests.sessions.Session.send", autospec=True) as send:
        yield send


@pytest.fixture
def redis_client() -> Iterator[MagicMock]:
    stored: dict[str, str] = {}
    client = MagicMock()
    client.exists.side_effect = lambda key: int(key in stored)
    client.get.side_effect = stored.get
    client.set.side_effect = lambda key, value, ex: stored.update({key: value})
    client.delete.side_effect = lambda key: stored.pop(key, None)
    with (
        override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT=6379),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
            return_value=client,
        ),
    ):
        yield client


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://api.retellai.com/v3/list-calls"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result
