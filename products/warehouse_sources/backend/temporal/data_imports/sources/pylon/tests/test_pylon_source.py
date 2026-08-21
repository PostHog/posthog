import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pylon import PylonSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon import source as pylon_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.source import PylonSource


def _config(api_token: str = "token") -> PylonSourceConfig:
    return PylonSourceConfig.from_dict({"api_token": api_token})


class TestPylonGetSchemas:
    def test_only_issues_supports_incremental(self) -> None:
        schemas = PylonSource().get_schemas(_config(), team_id=1)
        incremental = {s.name for s in schemas if s.supports_incremental}
        assert incremental == {"issues"}

    def test_issues_advertises_created_at_incremental_field(self) -> None:
        schemas = PylonSource().get_schemas(_config(), team_id=1, names=["issues"])
        fields = schemas[0].incremental_fields
        assert [f["field"] for f in fields] == ["created_at"]


class TestPylonValidateCredentials:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Pylon API token"))])
    def test_validate_credentials(self, _name: str, api_returns: bool, expected: tuple[bool, str | None]) -> None:
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon_source_module, "validate_pylon_credentials", lambda token: api_returns)
            result = PylonSource().validate_credentials(_config(), team_id=1)
        assert result == expected


class TestPylonSourceForPipeline:
    def test_plumbs_args_into_pylon_source(self) -> None:
        captured: dict = {}

        def _fake_pylon_source(**kwargs: object):
            captured.update(kwargs)
            return MagicMock()

        inputs = MagicMock()
        inputs.schema_name = "issues"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"
        inputs.incremental_field = "created_at"
        manager = MagicMock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon_source_module, "pylon_source", _fake_pylon_source)
            PylonSource().source_for_pipeline(_config("secret"), manager, inputs)

        assert captured["api_token"] == "secret"
        assert captured["endpoint"] == "issues"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-06-01T00:00:00Z"
        assert captured["resumable_source_manager"] is manager

    def test_passes_none_last_value_when_not_incremental(self) -> None:
        captured: dict = {}

        def _fake_pylon_source(**kwargs: object):
            captured.update(kwargs)
            return MagicMock()

        inputs = MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon_source_module, "pylon_source", _fake_pylon_source)
            PylonSource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
