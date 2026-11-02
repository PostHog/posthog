from collections.abc import Iterator

import pytest
from unittest.mock import patch

from django.test import override_settings

import fakeredis
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.turso import TursoSourceConfig


@pytest.fixture
def config() -> TursoSourceConfig:
    return TursoSourceConfig(organization_slug="example-org", api_token="test-platform-token")


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="databases",
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
def resume_storage() -> Iterator[None]:
    with (
        override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT=6379),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
            return_value=fakeredis.FakeRedis(),
        ),
    ):
        yield
