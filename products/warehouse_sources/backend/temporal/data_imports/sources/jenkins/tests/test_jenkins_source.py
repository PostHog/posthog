from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JenkinsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.jenkins import JenkinsResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.source import JenkinsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> JenkinsSourceConfig:
    return JenkinsSourceConfig(host="https://jenkins.example.com", username="ci-bot", api_token="token")


class TestJenkinsSource:
    def setup_method(self) -> None:
        self.source = JenkinsSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.JENKINS

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible (no unreleasedSource) and labelled ALPHA.
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        by_name: dict[str, SourceFieldInputConfig] = {}
        for field in config.fields:
            assert isinstance(field, SourceFieldInputConfig)
            by_name[field.name] = field
        assert set(by_name) == {"host", "username", "api_token"}
        # Only the API token is a secret; the URL and username are not.
        assert by_name["api_token"].secret is True
        assert by_name["host"].secret is False
        assert by_name["username"].secret is False

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = {s.name for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas == set(ENDPOINTS)

    @parameterized.expand(
        [
            # Jenkins has no server-side time filter; builds sync incrementally via newest-first index
            # windowing on the derived start time, jobs are full refresh (no stable cursor).
            ("builds", True),
            ("jobs", False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, expected: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas[endpoint].supports_incremental is expected
        assert schemas[endpoint].supports_append is expected

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=self.team_id, names=["builds"])
        assert [s.name for s in schemas] == ["builds"]

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://jenkins.example.com/api/json"),
            ("forbidden", "403 Client Error: Forbidden for url: https://jenkins.example.com/job/x/api/json"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='jenkins.example.com', port=443): Read timed out."),
            ("server_error", "Jenkins API error (retryable): status=503"),
            ("rate_limited", "Jenkins API error (retryable): status=429"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas does no I/O, so the static catalog is safe to render in public docs.
        assert self.source.lists_tables_without_credentials is True
        assert {t["name"] for t in self.source.get_documented_tables()} == set(ENDPOINTS)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is JenkinsResumeConfig

    def test_validate_credentials_delegates_when_host_valid(self) -> None:
        with mock.patch.object(self.source, "_validate_host", return_value=(True, None)):
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.source.validate_jenkins_credentials",
                return_value=(True, None),
            ) as mock_validate:
                result = self.source.validate_credentials(_config(), team_id=self.team_id, schema_name="builds")
        assert result == (True, None)
        mock_validate.assert_called_once_with("https://jenkins.example.com", "ci-bot", "token", "builds")

    def test_validate_credentials_rejects_bad_host_without_probing(self) -> None:
        with mock.patch.object(self.source, "_validate_host", return_value=(False, "bad host")):
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.source.validate_jenkins_credentials"
            ) as mock_validate:
                result = self.source.validate_credentials(_config(), team_id=self.team_id)
        assert result == (False, "bad host")
        mock_validate.assert_not_called()

    @parameterized.expand(
        [
            ("cloud_http_rejected", True, "http://jenkins.example.com", False),
            ("cloud_https_ok", True, "https://jenkins.example.com", True),
            ("self_hosted_http_ok", False, "http://jenkins.local", True),
        ]
    )
    def test_validate_host_https_requirement_on_cloud(
        self, _name: str, is_cloud: bool, host: str, expected_ok: bool
    ) -> None:
        # On Cloud the API token would otherwise be sent in cleartext to a customer-supplied http host.
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.source.is_cloud",
            return_value=is_cloud,
        ):
            with mock.patch.object(self.source, "is_database_host_valid", return_value=(True, None)):
                ok, _error = self.source._validate_host(host, self.team_id)
        assert ok is expected_ok

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "builds"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = MagicMock()
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        with mock.patch.object(self.source, "_validate_host", return_value=(True, None)):
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.source.jenkins_source",
                side_effect=fake_source,
            ):
                self.source.source_for_pipeline(_config(), manager, inputs)

        assert captured["host"] == "https://jenkins.example.com"
        assert captured["username"] == "ci-bot"
        assert captured["api_token"] == "token"
        assert captured["endpoint"] == "builds"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "jobs"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        with mock.patch.object(self.source, "_validate_host", return_value=(True, None)):
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.source.jenkins_source",
                side_effect=fake_source,
            ):
                self.source.source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_raises_on_invalid_host(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "jobs"
        with mock.patch.object(self.source, "_validate_host", return_value=(False, "Jenkins URL must use https")):
            try:
                self.source.source_for_pipeline(_config(), MagicMock(), inputs)
            except ValueError as e:
                assert "https" in str(e)
            else:
                raise AssertionError("expected ValueError for invalid host")
