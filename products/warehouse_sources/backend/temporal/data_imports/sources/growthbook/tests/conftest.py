from collections.abc import Iterator

import pytest
from unittest.mock import MagicMock, patch

import responses
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.growthbook import (
    GrowthBookSourceConfig,
)


@pytest.fixture
def config() -> GrowthBookSourceConfig:
    return GrowthBookSourceConfig.from_dict({"api_key": "secret_test_growthbook"})


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="features",
        schema_id="schema-test",
        source_id="source-test",
        team_id=123,
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
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


@pytest.fixture
def http() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as http:
        yield http


@pytest.fixture(autouse=True)
def safe_host() -> Iterator[MagicMock]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.growthbook.growthbook._is_host_safe",
        return_value=(True, None),
    ) as safe:
        yield safe
