from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.source import DingConnectSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dingconnect import (
    DingConnectSourceConfig,
)


class TestValidateCredentials:
    def test_valid_credentials(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            ok, error = DingConnectSource().validate_credentials(DingConnectSourceConfig(api_key="key"), team_id=1)

        assert ok is True
        assert error is None
        assert network.requests_log[0].path == "/api/V1/GetBalance"

    def test_invalid_credentials(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            ok, error = DingConnectSource().validate_credentials(DingConnectSourceConfig(api_key="key"), team_id=1)

        assert ok is False
        assert error == "Invalid DingConnect API key"
        assert network.requests_log[0].path == "/api/V1/GetBalance"


class TestSourceForPipeline:
    def test_plumbs_through_to_transport(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = object()

        def fake_ding_connect_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "ding_connect_source", fake_ding_connect_source)

        manager = MagicMock()
        inputs = MagicMock(schema_name="TransferRecords", team_id=7, job_id="job-1")
        result = DingConnectSource().source_for_pipeline(MagicMock(api_key="key"), manager, inputs)

        assert result is sentinel
        assert captured["api_key"] == "key"
        assert captured["endpoint"] == "TransferRecords"
        assert captured["team_id"] == 7
        assert captured["job_id"] == "job-1"
        assert captured["resumable_source_manager"] is manager


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.dingconnect.com/api/V1/GetCountries",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.dingconnect.com/api/V1/GetProducts",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = DingConnectSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.dingconnect.com"),
            ("read_timeout", "HTTPSConnectionPool(host='api.dingconnect.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable_errors = DingConnectSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
