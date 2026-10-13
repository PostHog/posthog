import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.source import CoolifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coolify import (
    CoolifySourceConfig,
)


def _config() -> CoolifySourceConfig:
    return CoolifySourceConfig(base_url="https://coolify.example.com", api_token="coolify-token")


class TestCoolifySourceForPipeline:
    @pytest.mark.parametrize(
        "endpoint,expected_pk,expected_partition_key",
        [
            pytest.param("applications", ["uuid"], "created_at", id="applications_uuid_pk_partitioned"),
            # The deployment queue row's uuid, unique across the instance, so no parent
            # component is needed in the key.
            pytest.param("deployments", ["deployment_uuid"], "created_at", id="deployments_own_uuid_pk"),
            # Teams have no uuid, and projects/servers return no creation timestamp to
            # partition on.
            pytest.param("teams", ["id"], "created_at", id="teams_id_pk"),
            pytest.param("projects", ["uuid"], None, id="projects_no_partition"),
            pytest.param("servers", ["uuid"], None, id="servers_no_partition"),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.coolify.source.coolify_source")
    def test_plumbs_primary_keys_and_partitioning(
        self, mock_source: MagicMock, endpoint: str, expected_pk: list[str], expected_partition_key: str | None
    ) -> None:
        resource = MagicMock()
        resource.name = endpoint
        resource.column_hints = None
        mock_source.return_value = resource

        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.team_id = 1
        inputs.job_id = "job-1"

        response = CoolifySource().source_for_pipeline(_config(), inputs)

        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        if expected_partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [expected_partition_key]
        else:
            assert response.partition_mode is None
