from collections.abc import Iterator

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

import structlog
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sim import SimSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.sim import SimResumeConfig


@pytest.fixture
def config() -> SimSourceConfig:
    return SimSourceConfig(api_key="sim_fake_key", workspace_id="workspace-example")


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="logs",
        schema_id="schema-example",
        source_id="source-example",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-example",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.fixture
def http() -> Iterator[Mocker]:
    with Mocker() as mock:
        yield mock


@pytest.fixture
def redis_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    monkeypatch.setattr(settings, "DATA_WAREHOUSE_REDIS_HOST", "localhost")
    monkeypatch.setattr(settings, "DATA_WAREHOUSE_REDIS_PORT", 6379)
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client"
    ) as get_client:
        client = get_client.return_value
        client.exists.return_value = 0
        yield client


@pytest.fixture
def manager(inputs: SourceInputs, redis_client: MagicMock) -> ResumableSourceManager[SimResumeConfig]:
    return ResumableSourceManager(inputs, SimResumeConfig)
