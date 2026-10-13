import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
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
    def test_plumbs_primary_keys_and_partitioning(
        self, endpoint: str, expected_pk: list[str], expected_partition_key: str | None
    ) -> None:
        result = SourceDriver(CoolifySource(), _config()).run(endpoint, [ScriptedResponse(json=[])])
        assert result.raised is None
        response = result.response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        if expected_partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [expected_partition_key]
        else:
            assert response.partition_mode is None
