import json
from collections.abc import Callable, Iterator

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import structlog
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sevdesk import (
    SevdeskSourceConfig,
)


@pytest.fixture
def source_config() -> SevdeskSourceConfig:
    return SevdeskSourceConfig(api_token="0" * 32)


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="Invoice",
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="test-job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.fixture
def response() -> Callable[..., Response]:
    def make_response(body: object, status: int = 200) -> Response:
        result = Response()
        result.status_code = status
        result.url = "https://my.sevdesk.de/api/v1/Contact"
        result.headers["Content-Type"] = "application/json"
        result._content = json.dumps(body).encode()
        return result

    return make_response


@pytest.fixture
def http(response: Callable[..., Response]) -> Iterator[MagicMock]:
    with patch("requests.Session.send", return_value=response({"objects": []})) as send:
        yield send


@pytest.fixture
def redis() -> Iterator[MagicMock]:
    values: dict[str, str] = {}
    client = MagicMock()
    client.get.side_effect = values.get
    client.set.side_effect = lambda key, value, **kwargs: values.update({key: value})
    with (
        override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT=6379),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
            return_value=client,
        ),
    ):
        yield client
