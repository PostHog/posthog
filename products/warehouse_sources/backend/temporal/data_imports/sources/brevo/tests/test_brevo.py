import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo import (
    BREVO_BASE_URL,
    BrevoResumeConfig,
    _build_base_params,
    _format_datetime,
    brevo_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.settings import BREVO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = f"{BREVO_BASE_URL}/contacts"
    resp.reason = "OK" if status_code == 200 else "Client Error"
    resp.headers["Content-Type"] = "application/json"
    return resp


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _drive_get_rows(
    endpoint: str,
    manager: MagicMock,
    responses: list[Response],
    **kwargs: Any,
) -> tuple[list[str], list[list[dict[str, Any]]]]:
    sent_urls: list[str] = []
    response_iter = iter(responses)

    def fake_get(url: str, headers: Any = None, timeout: Any = None) -> Response:
        sent_urls.append(url)
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo.make_tracked_session"
    ) as MockSession:
        MockSession.return_value.get.side_effect = fake_get
        rows = list(
            get_rows(
                api_key="test-key",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )

    return sent_urls, rows


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

    def test_no_plus_offset(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, tzinfo=UTC))


class TestBuildBaseParams:
    def test_paginated_endpoint_sorts_ascending(self) -> None:
        params = _build_base_params(BREVO_ENDPOINTS["contacts"], False, None, None)
        assert params == {"sort": "asc"}

    def test_non_paginated_endpoint_has_no_sort(self) -> None:
        params = _build_base_params(BREVO_ENDPOINTS["senders"], False, None, None)
        assert params == {}

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

    def test_no_filter_on_first_sync(self) -> None:
        params = _build_base_params(BREVO_ENDPOINTS["contacts"], True, None, "modifiedAt")
        assert "modifiedSince" not in params
        assert "createdSince" not in params

    def test_unknown_incremental_field_is_ignored(self) -> None:
        params = _build_base_params(BREVO_ENDPOINTS["contacts"], True, datetime(2026, 3, 4, tzinfo=UTC), "nonexistent")
        assert params == {"sort": "asc"}


class TestGetRowsPagination:
    def test_offset_advances_and_terminates_on_short_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_response({"contacts": [{"id": 1}, {"id": 2}], "count": 3}),
            _make_response({"contacts": [{"id": 3}], "count": 3}),
        ]
        sent_urls, rows = _drive_get_rows("contacts", manager, responses)

        offsets = [_query(u).get("offset", [None])[0] for u in sent_urls]
        assert offsets == ["0", "2"]
        assert rows == [[{"id": 1}, {"id": 2}], [{"id": 3}]]

    def test_saves_state_after_each_non_terminal_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_response({"contacts": [{"id": 1}, {"id": 2}]}),
            _make_response({"contacts": [{"id": 3}]}),
        ]
        _drive_get_rows("contacts", manager, responses)

        saved = [saved_call.args[0] for saved_call in manager.save_state.call_args_list]
        assert saved == [BrevoResumeConfig(offset=2)]

    def test_single_terminal_page_does_not_save_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 1000)
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"contacts": [{"id": 1}]})]
        _drive_get_rows("contacts", manager, responses)

        manager.save_state.assert_not_called()

    def test_resume_seeds_starting_offset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(BREVO_ENDPOINTS["contacts"], "page_size", 2)
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BrevoResumeConfig(offset=4)

        responses = [_make_response({"contacts": [{"id": 5}]})]
        sent_urls, _ = _drive_get_rows("contacts", manager, responses)

        assert _query(sent_urls[0])["offset"] == ["4"]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"contacts": [{"id": 1}]})]
        _drive_get_rows("contacts", manager, responses)

        manager.load_state.assert_not_called()

    def test_empty_page_yields_nothing(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"contacts": [], "count": 0})]
        _, rows = _drive_get_rows("contacts", manager, responses)

        assert rows == []


class TestGetRowsNonPaginated:
    def test_senders_fetched_once_without_pagination_params(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"senders": [{"id": 1}, {"id": 2}]})]
        sent_urls, rows = _drive_get_rows("senders", manager, responses)

        assert len(sent_urls) == 1
        assert urlsplit(sent_urls[0]).query == ""
        assert rows == [[{"id": 1}, {"id": 2}]]
        manager.save_state.assert_not_called()


class TestGetRowsErrors:
    def test_non_retryable_status_raises(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"message": "Key not found", "code": "unauthorized"}, status_code=401)]
        with pytest.raises(HTTPError):
            _drive_get_rows("contacts", manager, responses)

    @pytest.mark.parametrize(
        ("endpoint", "body"),
        [
            # Brevo omits the array key entirely for an empty collection (just {"count": 0}).
            ("email_campaigns", {"count": 0}),
            ("sms_campaigns", {"count": 0}),
            ("contact_segments", {"count": 0}),
            # Some responses set the key to null instead of omitting it.
            ("email_campaigns", {"campaigns": None, "count": 0}),
        ],
    )
    def test_missing_or_null_envelope_key_yields_nothing(self, endpoint: str, body: dict[str, Any]) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _, rows = _drive_get_rows(endpoint, manager, [_make_response(body)])

        assert rows == []
        manager.save_state.assert_not_called()


class TestGetRowsSession:
    def test_session_disables_transport_retry_and_redacts_key(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_response({"contacts": [{"id": 1}]})
            list(
                get_rows(
                    api_key="test-key",
                    endpoint="contacts",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        kwargs = MockSession.call_args.kwargs
        assert kwargs["retry"].total == 0
        assert kwargs["redact_values"] == ("test-key",)
        assert kwargs["headers"]["api-key"] == "test-key"
        # Session is created once and reused across the sync.
        MockSession.assert_called_once()
        MockSession.return_value.close.assert_called_once()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_response({}, status_code=status_code)
            assert validate_credentials("test-key") is expected

    def test_validate_credentials_network_error_returns_false(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.side_effect = Exception("network down")
            assert validate_credentials("test-key") is False


class TestBrevoSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expects_partition"),
        [
            ("contacts", True),
            ("email_campaigns", True),
            ("sms_campaigns", True),
            ("contact_lists", False),
            ("contact_folders", False),
            ("contact_segments", False),
            ("email_templates", False),
            ("senders", False),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expects_partition: bool) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = brevo_source(
            api_key="test-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["createdAt"]
            assert response.partition_format == "week"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
