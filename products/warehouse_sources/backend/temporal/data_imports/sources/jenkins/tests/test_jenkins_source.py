from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jenkins import (
    JenkinsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.source import JenkinsSource


def _config() -> JenkinsSourceConfig:
    return JenkinsSourceConfig(host="https://jenkins.example.com", username="ci-bot", api_token="token")


class TestJenkinsSource:
    def setup_method(self) -> None:
        self.source = JenkinsSource()
        self.team_id = 123

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
