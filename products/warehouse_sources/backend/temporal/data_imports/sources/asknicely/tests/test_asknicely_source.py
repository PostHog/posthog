from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.asknicely import build_responses_url
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source import AsknicelySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asknicely import (
    AsknicelySourceConfig,
)


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "responses",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestAsknicelySource:
    def setup_method(self) -> None:
        self.source = AsknicelySource()
        self.team_id = 123
        self.config = AsknicelySourceConfig(subdomain="acme", api_key="test-key")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Changing the subdomain retargets which AskNicely tenant the stored key is
        # sent to, so it must force the API key to be re-entered.
        assert self.source.connection_host_fields == ["subdomain"]

    @pytest.mark.parametrize("subdomain", ["not a subdomain", "acme.asknice.ly", "evil/../path", ""])
    def test_validate_credentials_rejects_bad_subdomain_without_a_request(self, subdomain: str) -> None:
        config = AsknicelySourceConfig(subdomain=subdomain, api_key="test-key")

        with scripted_network([]) as network:
            is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None and "subdomain" in error_message
        assert network.requests_log == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid"),
        [
            ((True, None), True),
            ((False, "Invalid AskNicely API key"), False),
        ],
    )
    def test_validate_credentials_delegates_to_transport(
        self,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
    ) -> None:
        status = 200 if expected_valid else 401
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if mock_return[1] is None:
            assert error_message is None
        else:
            assert error_message is not None and error_message.startswith(mock_return[1])
        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.url == build_responses_url("acme", page_number=1, since_time=0, page_size=1)
        assert request.headers["x-apikey"] == "test-key"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source.asknicely_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="responded",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            subdomain="acme",
            api_key="test-key",
            endpoint="responses",
            team_id=123,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

    def test_source_for_pipeline_drops_last_value_on_full_refresh(self) -> None:
        # A stale watermark left over from a previous incremental run must not leak into a
        # full-refresh sync, or the refresh would silently skip older responses.
        result = SourceDriver(self.source, self.config).run(
            "responses",
            [ScriptedResponse(json={"success": True, "data": []})],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.urls == [build_responses_url("acme", page_number=1, since_time=0)]
