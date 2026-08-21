import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.source import GitLabSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGitLabSource:
    def setup_method(self):
        self.source = GitLabSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.gitlab_host = "https://gitlab.com"
        self.config.personal_access_token = "glpat-token"
        self.config.project = "group/project"

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GITLAB

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["gitlab_host"]

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("issues", True),
            ("merge_requests", True),
            ("commits", True),
            ("pipelines", True),
            ("releases", False),
            ("milestones", False),
            ("branches", False),
            ("tags", False),
            ("labels", False),
            ("members", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])
        assert len(schemas) == 1
        assert schemas[0].name == "issues"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
