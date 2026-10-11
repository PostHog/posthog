import pytest
from unittest.mock import MagicMock

import structlog

from sources.productive._config import ProductiveSourceConfig
from sources.sdk import ResumableSourceManager, SourceInputs


@pytest.fixture
def config() -> ProductiveSourceConfig:
    return ProductiveSourceConfig(api_token="test-productive-token", organization_id="123")


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="projects",
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field="updated_at",
        incremental_field_type=None,
        job_id="test-job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.fixture
def resume_manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager
