from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.source import ZendeskSellSource


class TestValidateCredentials:
    @parameterized.expand(
        [("valid", True, (True, None)), ("invalid", False, (False, "Invalid Zendesk Sell access token"))]
    )
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        config = MagicMock(access_token="token")
        with patch.object(source_module, "validate_zendesk_sell_credentials", return_value=probe_result):
            assert ZendeskSellSource().validate_credentials(config, team_id=1) == expected


class TestSourceForPipeline:
    def test_plumbs_config_and_inputs_into_source_response(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = SourceResponse(name="deals", items=lambda: iter(()), primary_keys=["id"])

        def fake_source(**kwargs: Any) -> SourceResponse:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "zendesk_sell_source", fake_source)

        config = MagicMock(access_token="my-token")
        manager = MagicMock()
        inputs = MagicMock(schema_name="deals")
        inputs.logger = MagicMock()

        result = ZendeskSellSource().source_for_pipeline(config, manager, inputs)

        assert result is sentinel
        assert captured["access_token"] == "my-token"
        assert captured["endpoint"] == "deals"
        assert captured["resumable_source_manager"] is manager
