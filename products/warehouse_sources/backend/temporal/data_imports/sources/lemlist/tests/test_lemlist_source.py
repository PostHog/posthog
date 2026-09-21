from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.source import LemlistSource


def _config(api_key: str = "key") -> Any:
    return MagicMock(api_key=api_key)


class TestVersioning:
    def test_supports_v1_and_v2_defaulting_to_v2(self) -> None:
        source = LemlistSource()
        assert source.supported_versions == ("v1", "v2")
        # New sources are stamped with default_version; v2 is lemlist's current version.
        assert source.default_version == "v2"


class TestValidateCredentials:
    def test_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_lemlist_credentials", lambda _key: True)
        assert LemlistSource().validate_credentials(_config(), team_id=1) == (True, None)

    def test_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_lemlist_credentials", lambda _key: False)
        ok, error = LemlistSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.lemlist.com/api/team"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.lemlist.com/api/campaigns?version=v2"),
            ("not_found", "404 Client Error: Not Found for url: https://api.lemlist.com/api/team"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        keys = LemlistSource().get_non_retryable_errors()
        assert any(key in observed for key in keys)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.lemlist.com/api/activities"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.lemlist.com/api/team"),
            ("timeout", "HTTPSConnectionPool(host='api.lemlist.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        keys = LemlistSource().get_non_retryable_errors()
        assert not any(key in observed for key in keys)


class TestSourceForPipeline:
    def test_plumbs_inputs_into_lemlist_source(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        monkeypatch.setattr(source_module, "lemlist_source", fake_source)

        manager = MagicMock()
        inputs = MagicMock(
            schema_name="activities",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-05-11T00:00:00Z",
            api_version="v1",
        )
        result: Any = LemlistSource().source_for_pipeline(_config("secret"), manager, inputs)

        assert result == "response"
        assert captured["api_key"] == "secret"
        assert captured["endpoint"] == "activities"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-05-11T00:00:00Z"
        # A present pin is honored verbatim; a NULL pin would resolve to default_version.
        assert captured["api_version"] == "v1"

    def test_drops_last_value_when_not_incremental(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(source_module, "lemlist_source", lambda **kwargs: captured.update(kwargs))

        inputs = MagicMock(
            schema_name="campaigns",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-05-11T00:00:00Z",
        )
        LemlistSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert captured["db_incremental_field_last_value"] is None


class TestCanonicalDescriptions:
    def test_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
