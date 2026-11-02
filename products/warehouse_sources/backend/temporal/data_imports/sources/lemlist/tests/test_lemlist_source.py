from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lemlist import (
    LemlistSourceConfig,
)
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
            ("not_found", "404 Client Error: Not Found for url: https://api.lemlist.com/api/team"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        keys = LemlistSource().get_non_retryable_errors()
        assert any(key in observed for key in keys)


class TestSourceForPipeline:
    def test_plumbs_inputs_into_lemlist_source(self) -> None:
        driver = SourceDriver(LemlistSource(), LemlistSourceConfig(api_key="secret"))
        activities = driver.run(
            "activities",
            [ScriptedResponse(json=[{"_id": "act_1"}])],
            incremental_field="createdAt",
            db_incremental_field_last_value="2026-05-11T00:00:00Z",
            api_version="v1",
        )
        assert activities.raised is None
        assert activities.paths == ["/api/activities"]
        assert activities.rows == [{"_id": "act_1"}]
        assert activities.requests[0].headers["authorization"] == "Basic OnNlY3JldA=="
        assert activities.params("minDate") == ["2026-05-11T00:00:00Z"]

        # A present pin is honored verbatim; a NULL pin would resolve to default_version.
        team = driver.run("team", [ScriptedResponse(json={"_id": "team_1"})], api_version="v1")
        assert team.raised is None
        assert team.params("version") == [None]

    def test_drops_last_value_when_not_incremental(self) -> None:
        result = SourceDriver(LemlistSource(), LemlistSourceConfig(api_key="key")).run(
            "activities",
            [ScriptedResponse(json=[{"_id": "act_1"}])],
            db_incremental_field_last_value="2026-05-11T00:00:00Z",
        )
        assert result.raised is None
        assert result.requests[0].param("minDate") is None


class TestCanonicalDescriptions:
    def test_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
