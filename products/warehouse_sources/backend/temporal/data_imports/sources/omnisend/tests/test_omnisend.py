import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend import (
    OMNISEND_BASE_URL,
    OmnisendResumeConfig,
    get_rows,
    omnisend_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import OMNISEND_ENDPOINTS


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = f"{OMNISEND_BASE_URL}/contacts"
    resp.reason = "OK" if status_code == 200 else "Client Error"
    resp.headers["Content-Type"] = "application/json"
    return resp


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _drive_get_rows(
    endpoint: str,
    manager: MagicMock,
    responses: list[Response],
) -> tuple[list[str], list[list[dict[str, Any]]]]:
    sent_urls: list[str] = []
    response_iter = iter(responses)

    def fake_get(url: str, timeout: Any = None) -> Response:
        sent_urls.append(url)
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend.make_tracked_session"
    ) as MockSession:
        MockSession.return_value.get.side_effect = fake_get
        rows = list(
            get_rows(
                api_key="test-key",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
        )

    return sent_urls, rows


def _next_url(offset: int) -> str:
    return f"{OMNISEND_BASE_URL}/contacts?limit=250&offset={offset}"


class TestGetRowsPagination:
    def test_follows_paging_next_until_exhausted(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_response({"contacts": [{"contactID": "1"}], "paging": {"next": _next_url(250)}}),
            _make_response({"contacts": [{"contactID": "2"}], "paging": {"next": None}}),
        ]
        sent_urls, rows = _drive_get_rows("contacts", manager, responses)

        # First request hits the limit-seeded base URL; second follows paging.next verbatim.
        assert _query(sent_urls[0])["limit"] == ["250"]
        assert "offset" not in _query(sent_urls[0])
        assert sent_urls[1] == _next_url(250)
        assert rows == [[{"contactID": "1"}], [{"contactID": "2"}]]

    def test_saves_state_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_response({"contacts": [{"contactID": "1"}], "paging": {"next": _next_url(250)}}),
            _make_response({"contacts": [{"contactID": "2"}], "paging": {"next": None}}),
        ]
        _drive_get_rows("contacts", manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [OmnisendResumeConfig(next_url=_next_url(250))]

    def test_single_terminal_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"contacts": [{"contactID": "1"}], "paging": {"next": None}})]
        _drive_get_rows("contacts", manager, responses)

        manager.save_state.assert_not_called()

    def test_missing_paging_block_terminates(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"contacts": [{"contactID": "1"}]})]
        sent_urls, rows = _drive_get_rows("contacts", manager, responses)

        assert len(sent_urls) == 1
        assert rows == [[{"contactID": "1"}]]
        manager.save_state.assert_not_called()

    def test_empty_page_yields_nothing(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"contacts": [], "paging": {"next": None}})]
        _, rows = _drive_get_rows("contacts", manager, responses)

        assert rows == []


class TestGetRowsResume:
    def test_resume_seeds_starting_url(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = OmnisendResumeConfig(next_url=_next_url(500))

        responses = [_make_response({"contacts": [{"contactID": "6"}], "paging": {"next": None}})]
        sent_urls, _ = _drive_get_rows("contacts", manager, responses)

        assert sent_urls[0] == _next_url(500)
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"contacts": [{"contactID": "1"}], "paging": {"next": None}})]
        _drive_get_rows("contacts", manager, responses)

        manager.load_state.assert_not_called()


class TestGetRowsErrors:
    @pytest.mark.parametrize("status_code", [401, 403, 422])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_response({"error": "Forbidden"}, status_code=status_code)]
        with pytest.raises(HTTPError):
            _drive_get_rows("contacts", manager, responses)

    def test_missing_envelope_key_raises(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        # 200 OK with an unexpected body shape must fail loudly, not sync zero rows.
        responses = [_make_response({"unexpected": [], "paging": {"next": None}})]
        with pytest.raises(KeyError):
            _drive_get_rows("contacts", manager, responses)


class TestGetRowsSession:
    def test_session_disables_transport_retry_redacts_key_and_closes(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_response(
                {"contacts": [{"contactID": "1"}], "paging": {"next": None}}
            )
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
        assert kwargs["headers"]["X-API-KEY"] == "test-key"
        MockSession.assert_called_once()
        MockSession.return_value.close.assert_called_once()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_ok"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_response({}, status_code=status_code)
            ok, code = validate_credentials("test-key")
        assert ok is expected_ok
        assert code == status_code

    def test_validate_credentials_network_error(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.side_effect = Exception("network down")
            ok, code = validate_credentials("test-key")
        assert ok is False
        assert code is None


class TestOmnisendSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "primary_key", "expects_partition"),
        [
            ("contacts", "contactID", True),
            ("campaigns", "campaignID", True),
            ("carts", "cartID", True),
            ("orders", "orderID", True),
            ("products", "productID", True),
            ("categories", "categoryID", False),
        ],
    )
    def test_source_response_shape(self, endpoint: str, primary_key: str, expects_partition: bool) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = omnisend_source(
            api_key="test-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,
        )

        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == "asc"

        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["createdAt"]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_every_endpoint_partition_key_is_stable(self) -> None:
        # Partition keys must be creation-time fields, never mutable ones.
        for config in OMNISEND_ENDPOINTS.values():
            if config.partition_key is not None:
                assert config.partition_key == "createdAt"
