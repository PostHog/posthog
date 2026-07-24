import json
from base64 import b64encode
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.tickettailor import (
    PAGE_SIZE,
    TicketTailorResumeConfig,
    tickettailor_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the tickettailor module.
TICKETTAILOR_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.tickettailor.make_tracked_session"
)


def _page(items: list[dict[str, Any]] | None, *, next_link: str | None = None, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"links": {"next": next_link, "previous": None}}
    if not drop_data:
        body["data"] = items or []
    return _response(body)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _client_session(send_side_effect: Any) -> tuple[Session, list[Any]]:
    """A real ``requests.Session`` that runs prepare_request for real (so framework auth is applied)
    but mocks ``send``. Captures each prepared request so tests can read the auth header and the query
    params the paginator actually put on the wire."""
    session = Session()
    captured: list[Any] = []
    real_prepare = session.prepare_request

    def prepare(request: Any) -> Any:
        prepared = real_prepare(request)
        captured.append(prepared)
        return prepared

    session.prepare_request = prepare  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    session.send = mock.MagicMock(side_effect=send_side_effect)  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    return session, captured


def _query(prepared: Any) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(prepared.url).query).items()}


def _make_manager(resume_state: TicketTailorResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(manager: mock.MagicMock, responses: list[Response], endpoint: str = "orders") -> tuple[list[dict], list[Any]]:
    session, captured = _client_session(responses)
    with mock.patch(CLIENT_SESSION_PATCH, return_value=session):
        rows = _rows(
            tickettailor_source(
                api_key="tt-key",
                endpoint=endpoint,
                resumable_source_manager=manager,
                team_id=1,
                job_id="j",
            )
        )
    return rows, captured


class TestPagination:
    def test_follows_cursor_until_no_next_link(self) -> None:
        first_page = [{"id": f"or_{i}"} for i in range(PAGE_SIZE)]
        manager = _make_manager()
        rows, captured = _run(
            manager,
            [
                _page(first_page, next_link="https://api.tickettailor.com/v1/orders?starting_after=or_99"),
                _page([{"id": "or_100"}], next_link=None),
            ],
        )

        assert [r["id"] for r in rows] == [*(f"or_{i}" for i in range(PAGE_SIZE)), "or_100"]
        # First request carries only limit; the second advances via the last id of page one.
        assert _query(captured[0]) == {"limit": str(PAGE_SIZE)}
        assert _query(captured[1]) == {"limit": str(PAGE_SIZE), "starting_after": "or_99"}
        # Checkpoint saved once, after the first page (points at the next page); the null next link ends it.
        manager.save_state.assert_called_once_with(TicketTailorResumeConfig(cursor="or_99"))

    def test_single_page_without_next_link_makes_one_request_and_no_checkpoint(self) -> None:
        manager = _make_manager()
        rows, captured = _run(manager, [_page([{"id": "or_1"}, {"id": "or_2"}], next_link=None)])

        assert [r["id"] for r in rows] == ["or_1", "or_2"]
        assert len(captured) == 1
        manager.save_state.assert_not_called()

    def test_resumes_from_saved_cursor(self) -> None:
        manager = _make_manager(TicketTailorResumeConfig(cursor="or_50"))
        rows, captured = _run(manager, [_page([{"id": "or_51"}], next_link=None)])

        assert [r["id"] for r in rows] == ["or_51"]
        # The uncursored first page must never be fetched on resume.
        assert _query(captured[0]) == {"limit": str(PAGE_SIZE), "starting_after": "or_50"}

    def test_empty_first_page_yields_nothing_and_no_checkpoint(self) -> None:
        manager = _make_manager()
        rows, captured = _run(manager, [_page([], next_link=None)])

        assert rows == []
        assert len(captured) == 1
        manager.save_state.assert_not_called()

    def test_next_link_present_but_empty_page_stops(self) -> None:
        # A truthy next link with an empty page must still terminate (mirrors the old `or not items`).
        manager = _make_manager()
        rows, captured = _run(
            manager,
            [_page([], next_link="https://api.tickettailor.com/v1/orders?starting_after=or_x")],
        )

        assert rows == []
        assert len(captured) == 1
        manager.save_state.assert_not_called()


class TestMalformedBodyIsRetryable:
    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "or_1"}]),
            ("missing_data_key", {"links": {"next": None}}),
        ]
    )
    @mock.patch("tenacity.nap.time.sleep")
    def test_unexpected_shape_is_retried_then_reraised(self, _name: str, body: Any, _sleep: mock.MagicMock) -> None:
        # A 200 whose body isn't {"data": [...], ...} is treated as a transient truncation: retried
        # (up to the client's attempt cap) rather than ingested as a stray row.
        manager = _make_manager()
        with pytest.raises(RESTClientRetryableError):
            _run(manager, lambda *a, **k: _response(body))  # type: ignore[arg-type]


class TestAuth:
    def test_uses_http_basic_with_key_as_username(self) -> None:
        manager = _make_manager()
        _, captured = _run(manager, [_page([{"id": "or_1"}], next_link=None)])

        # Ticket Tailor authenticates via HTTP Basic with the key as the username and no password —
        # switching to e.g. a Bearer header would break every sync.
        expected = "Basic " + b64encode(b"tt-key:").decode()
        assert captured[0].headers["Authorization"] == expected
        assert captured[0].headers["Accept"] == "application/json"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Ticket Tailor API key"),
            # Ticket Tailor answers invalid/deleted keys with 403, not 401.
            ("forbidden", 403, False, "Invalid Ticket Tailor API key"),
            ("server_error", 500, False, "Ticket Tailor returned HTTP 500"),
        ]
    )
    @mock.patch(TICKETTAILOR_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("tt-key") == (expected_valid, expected_message)

    @mock.patch(TICKETTAILOR_SESSION_PATCH)
    def test_connection_error_maps_to_could_not_validate(self, mock_session: mock.MagicMock) -> None:
        # validate_via_probe swallows transport errors; the probe reports "not validated".
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("tt-key") == (False, "Could not validate Ticket Tailor API key")


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = tickettailor_source(
            api_key="tt-key",
            endpoint=endpoint,
            resumable_source_manager=_make_manager(),
            team_id=1,
            job_id="j",
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Lists come back newest-first; declaring asc would corrupt a future incremental watermark.
        assert response.sort_mode == "desc"
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None
