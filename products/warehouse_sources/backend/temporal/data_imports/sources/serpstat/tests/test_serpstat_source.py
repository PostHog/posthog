import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.serpstat import (
    SerpstatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.settings import AUTH_ERROR, QUOTA_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.source import SerpstatSource

RESOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.source.serpstat_resource"


@pytest.mark.parametrize("field", ["project_id", "project_region_id"])
@pytest.mark.parametrize("value", ["", "0", "-1", "abc", "1.5"])
def test_invalid_ids_do_not_call_api(field: str, value: str) -> None:
    config = SerpstatSourceConfig.from_dict(
        {"api_key": "example-token", "project_id": "123", "project_region_id": "456", field: value}
    )
    with patch(RESOURCE) as resource:
        valid, error = SerpstatSource().validate_credentials(config, 1)
    assert not valid
    assert error is not None
    assert "positive integer" in error
    resource.assert_not_called()


@pytest.mark.parametrize(
    "failure,expected",
    [
        (None, (True, None)),
        (ValueError(AUTH_ERROR), (False, AUTH_ERROR)),
        (ValueError(QUOTA_ERROR), (False, QUOTA_ERROR)),
        (RESTClientRetryableError("Unavailable"), (False, "Could not reach Serpstat. Try again later.")),
    ],
)
def test_credential_results(failure: Exception | None, expected: tuple[bool, str | None]) -> None:
    config = SerpstatSourceConfig(api_key="example-token", project_id="123", project_region_id="456")
    with patch(RESOURCE, side_effect=failure, return_value=[]) as resource:
        assert SerpstatSource().validate_credentials(config, 1) == expected
    resource.assert_called_once_with(config, "projects", 1, "", "v4", credential_check=True)


@pytest.mark.parametrize("incremental", [False, True])
def test_pipeline_does_not_apply_unavailable_incremental_filter(incremental: bool) -> None:
    config = SerpstatSourceConfig(api_key="example-token", project_id="123", project_region_id="456")
    inputs = MagicMock(
        schema_name="project_keywords",
        team_id=1,
        job_id="test-job",
        api_version=None,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2026-01-01",
    )
    manager = MagicMock()
    with patch(RESOURCE) as resource:
        response = SerpstatSource().source_for_pipeline(config, manager, inputs)
    resource.assert_called_once_with(config, "project_keywords", 1, "test-job", "v4", manager)
    assert response.primary_keys == ["project_id", "id"]
    assert response.partition_keys == ["added"]
    assert response.sort_mode == "asc"
