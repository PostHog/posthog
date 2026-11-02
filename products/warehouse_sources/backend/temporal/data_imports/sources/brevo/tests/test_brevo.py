from datetime import UTC, date, datetime

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo import (
    BrevoResumeConfig,
    _build_base_params,
    _format_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.settings import BREVO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.source import BrevoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.brevo import BrevoSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(BrevoSource(), BrevoSourceConfig(api_key="test-key"))


class TestFormatDatetime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestBuildBaseParams:
    @pytest.mark.parametrize(
        ("incremental_field", "expected_param"),
        [("createdAt", "createdSince"), ("modifiedAt", "modifiedSince")],
    )
    def test_incremental_field_maps_to_server_param(self, incremental_field: str, expected_param: str) -> None:
        params = _build_base_params(
            BREVO_ENDPOINTS["contacts"],
            True,
            datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field,
        )
        assert params[expected_param] == "2026-03-04T02:58:14.000Z"


class TestPagination:
    def test_offset_advances_and_terminates_on_short_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"contacts": [{"id": 1}, {"id": 2}], "count": 3}),
                ScriptedResponse(json={"contacts": [{"id": 3}], "count": 3}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.params("offset") == ["0", "2"]
        assert result.requests[0].param("limit") == "2"
        assert result.requests[0].param("sort") == "asc"

    def test_saves_state_after_each_non_terminal_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"contacts": [{"id": 1}, {"id": 2}]}),
                ScriptedResponse(json={"contacts": [{"id": 3}]}),
            ],
        )

        assert result.raised is None
        assert result.saved_states == [BrevoResumeConfig(offset=2)]

    def test_resume_seeds_starting_offset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        result = _driver().run(
            "contacts", [ScriptedResponse(json={"contacts": [{"id": 5}]})], resume_state=BrevoResumeConfig(offset=4)
        )

        assert result.raised is None
        assert result.params("offset") == ["4"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run("contacts", [ScriptedResponse(json={"contacts": [{"id": 1}]})])

        assert result.raised is None
        assert result.params("offset") == ["0"]

    def test_incremental_filter_param_is_sent(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json={"contacts": [{"id": 1}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="modifiedAt",
        )

        assert result.raised is None
        assert result.requests[0].param("modifiedSince") == "2026-03-04T02:58:14.000Z"


class TestNonPaginated:
    def test_senders_fetched_once_without_pagination_params(self) -> None:
        result = _driver().run("senders", [ScriptedResponse(json={"senders": [{"id": 1}, {"id": 2}]})])

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.queries == [{}]
        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.saved_states == []


class TestErrors:
    def test_non_retryable_status_raises(self) -> None:
        result = _driver().run(
            "contacts", [ScriptedResponse(status=401, json={"message": "Key not found", "code": "unauthorized"})]
        )

        assert isinstance(result.raised, HTTPError)


class TestSession:
    def test_session_redacts_key_and_sets_accept_header(self) -> None:
        result = _driver().run("contacts", [ScriptedResponse(json={"contacts": [{"id": 1}]})])

        # The api key travels via framework auth, so it's registered for value-based redaction
        # rather than being a plain client header.
        assert result.raised is None
        assert len(result.session_options) == 1
        assert result.session_options[0]["redact_values"] == ("test-key",)
        assert result.requests[0].headers["accept"] == "application/json"


class TestValidateCredentials:
    def test_validate_credentials_sends_api_key_header(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            assert validate_credentials("test-key") is True

        assert len(network.session_options) == 1
        assert network.session_options[0]["redact_values"] == ("test-key",)
        assert network.requests_log[0].headers["api-key"] == "test-key"

    def test_validate_credentials_network_error_returns_false(self) -> None:
        with scripted_network([OSError("network down")]):
            assert validate_credentials("test-key") is False
