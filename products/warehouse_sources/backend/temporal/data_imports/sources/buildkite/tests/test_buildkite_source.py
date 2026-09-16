from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source import BuildkiteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildkite import (
    BuildkiteSourceConfig,
)


def _config() -> BuildkiteSourceConfig:
    return BuildkiteSourceConfig(api_access_token="bkua_test", organization="my-org")


class TestBuildkiteSource:
    def setup_method(self) -> None:
        self.source = BuildkiteSource()
        self.team_id = 123

    def test_connection_host_fields_includes_organization(self) -> None:
        # The token is sent to api.buildkite.com against <organization>, so retargeting the
        # organization must force re-entry of the token.
        assert self.source.connection_host_fields == ["organization"]

    @parameterized.expand(
        [
            # Builds exposes a server-side timestamp filter, and jobs inherit it through the build
            # fan-out that drives them. Nothing else has one.
            ("builds", True, True),
            ("jobs", True, False),
            ("organizations", False, False),
            ("organization_members", False, False),
            ("pipelines", False, False),
            ("pipeline_schedules", False, False),
            ("agents", False, False),
            ("cluster_queues", False, False),
            ("teams", False, False),
            ("team_pipelines", False, False),
            ("test_suites", False, False),
            ("test_suite_runs", False, False),
            ("test_suite_tests", False, False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, incremental: bool, append: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        # A job restates after it is created (state, finished_at) and each incremental run re-walks
        # the trailing build window, so append would materialize the re-pulled rows as duplicates.
        assert schemas[endpoint].supports_append is append

    def test_jobs_is_off_by_default_and_says_why(self) -> None:
        # One request per build is enough API cost that the schema picker must not pre-select it.
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas["jobs"].should_sync_default is False
        assert schemas["jobs"].description is not None
        assert all(s.should_sync_default for s in schemas.values() if s.name != "jobs")

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.buildkite.com/v2/organizations/my-org/builds?per_page=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.buildkite.com/v2/organizations/my-org/agents",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.buildkite.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.buildkite.com/v2"),
            ("rate_limited", "HTTP 429 for https://api.buildkite.com/v2/organizations/my-org/builds"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Each declared endpoint should have a curated description so it isn't sent to the LLM.
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "builds"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "created_at"
        manager = MagicMock()

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source.buildkite_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), manager, inputs)

        assert captured["api_access_token"] == "bkua_test"
        assert captured["organization"] == "my-org"
        assert captured["endpoint"] == "builds"
        assert captured["team_id"] is inputs.team_id
        assert captured["job_id"] is inputs.job_id
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert captured["incremental_field"] == "created_at"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "pipelines"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source.buildkite_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
