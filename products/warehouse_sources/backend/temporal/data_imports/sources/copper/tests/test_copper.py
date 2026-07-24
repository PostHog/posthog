import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper import (
    COPPER_DEFAULT_PAGE_SIZE,
    CopperResumeConfig,
    _to_unix_seconds,
    copper_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the copper module.
COPPER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(items).encode() if items is not None else b""
    return resp


def _records(ids: list[int]) -> list[dict[str, Any]]:
    return [{"id": i, "date_created": 1700000000 + i, "date_modified": 1700000100 + i} for i in ids]


def _make_manager(resume_state: CopperResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's JSON body AT SEND TIME.

    The paginator injects `page_number` into a single body dict that's mutated in place across pages,
    so inspecting it after the run shows only the final state — snapshot a copy at prepare time.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(dict(request.json) if request.json else {})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return copper_source(
        api_key="key",
        user_email="user@example.com",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToUnixSeconds:
    @parameterized.expand(
        [
            ("none", None, None),
            ("int", 1700000000, 1700000000),
            ("float", 1700000000.7, 1700000000),
            ("numeric_string", "1700000000", 1700000000),
            ("bool_true", True, None),
            ("garbage", "not-a-number", None),
        ]
    )
    def test_scalar_coercion(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_unix_seconds(value) == expected

    def test_datetime_coercion(self) -> None:
        dt = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        assert _to_unix_seconds(dt) == int(dt.timestamp())

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime(2023, 11, 14, 22, 13, 20)
        assert _to_unix_seconds(naive) == int(datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC).timestamp())

    def test_date_treated_as_utc(self) -> None:
        assert _to_unix_seconds(date(2023, 11, 14)) == int(datetime(2023, 11, 14, tzinfo=UTC).timestamp())


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminates_on_short_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_records([1, 2]))])
        manager = _make_manager()

        rows = _rows(_source("people", manager))

        assert [r["id"] for r in rows] == [1, 2]
        # A short first page stops the loop with no extra empty-page request and no checkpoint.
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        manager = _make_manager()

        rows = _rows(_source("companies", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_page_after_each_full_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_a = _records(list(range(COPPER_DEFAULT_PAGE_SIZE)))
        full_b = _records(list(range(COPPER_DEFAULT_PAGE_SIZE, 2 * COPPER_DEFAULT_PAGE_SIZE)))
        tail = _records([99999])
        bodies = _wire(session, [_response(full_a), _response(full_b), _response(tail)])
        manager = _make_manager()

        rows = _rows(_source("people", manager))

        assert len(rows) == 2 * COPPER_DEFAULT_PAGE_SIZE + 1
        # Requests walk pages 1, 2, 3; a checkpoint pointing at the next page is saved after each
        # full page, and the short final page ends the loop without a checkpoint.
        assert [b["page_number"] for b in bodies] == [1, 2, 3]
        saved_pages = [call.args[0].page_number for call in manager.save_state.call_args_list]
        assert saved_pages == [2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response(_records([1]))])
        manager = _make_manager(CopperResumeConfig(page_number=4))

        _rows(_source("people", manager))

        assert bodies[0]["page_number"] == 4
        manager.load_state.assert_called_once()


class TestSearchBody:
    @parameterized.expand(
        [
            ("date_modified", "minimum_modified_date", "date_modified"),
            ("date_created", "minimum_created_date", "date_created"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sets_filter_and_sort(
        self, incremental_field: str, min_param: str, sort_field: str, MockSession
    ) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])
        manager = _make_manager()

        _rows(
            _source(
                "people",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field=incremental_field,
            )
        )

        body = bodies[0]
        assert body[min_param] == 1700000000
        assert body["sort_by"] == sort_field
        assert body["sort_direction"] == "asc"
        assert body["page_size"] == COPPER_DEFAULT_PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sorts_by_created_for_searchable(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])
        manager = _make_manager()

        _rows(_source("people", manager, should_use_incremental_field=False))

        body = bodies[0]
        assert body["sort_by"] == "date_created"
        assert "minimum_modified_date" not in body
        assert "minimum_created_date" not in body


class TestReferenceEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_get_no_body_and_no_resume(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([{"id": 1, "name": "Won"}])])
        manager = _make_manager()

        rows = _rows(_source("loss_reasons", manager))

        assert rows == [{"id": 1, "name": "Won"}]
        assert session.send.call_count == 1
        # GET reference endpoints carry no request body and never consult the resumable manager.
        assert bodies[0] == {}
        manager.can_resume.assert_not_called()


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("tenacity.nap.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_succeeds(self, _name: str, status_code: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, status_code=status_code), _response(_records([1]))])
        manager = _make_manager()

        rows = _rows(_source("people", manager))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2


class TestRedaction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_registers_api_key_for_redaction(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_records([1]))])

        _rows(_source("people", _make_manager()))

        assert MockSession.call_args.kwargs["redact_values"] == ("key",)


class TestSourceResponseMetadata:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metadata_for_searchable(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_records([1]))])

        response = _source("opportunities", _make_manager())
        rows = _rows(response)

        assert response.name == "opportunities"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date_created"]
        assert response.sort_mode == "asc"
        assert [r["id"] for r in rows] == [1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metadata_for_reference(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        response = _source("pipelines", _make_manager())

        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    @mock.patch(COPPER_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        valid, error = validate_credentials("key", "user@example.com")

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch(COPPER_SESSION_PATCH)
    def test_transport_error_maps_to_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        valid, error = validate_credentials("key", "user@example.com")

        assert valid is False
        assert error is not None

    @mock.patch(COPPER_SESSION_PATCH)
    def test_registers_api_key_for_redaction(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("secret-key", "user@example.com")

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)
