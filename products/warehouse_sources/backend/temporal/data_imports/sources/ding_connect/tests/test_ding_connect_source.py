from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.source import DingConnectSource


class TestValidateCredentials:
    def test_valid_credentials(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_ding_connect_credentials", lambda api_key: True)
        ok, error = DingConnectSource().validate_credentials(MagicMock(api_key="key"), team_id=1)
        assert ok is True
        assert error is None

    def test_invalid_credentials(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_ding_connect_credentials", lambda api_key: False)
        ok, error = DingConnectSource().validate_credentials(MagicMock(api_key="key"), team_id=1)
        assert ok is False
        assert error == "Invalid DingConnect API key"


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
