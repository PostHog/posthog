import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid import (
    SendGridResumeConfig,
    _offset_from_url,
    _to_epoch_seconds,
    get_status_code,
    sendgrid_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# get_status_code builds its own tracked session in the sendgrid module.
SENDGRID_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid.make_tracked_session"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SendGridResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; capture each request's params and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **overrides: Any) -> Any:
    return sendgrid_source("k", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **overrides)


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToEpochSeconds:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(1970, 1, 2), 86400),
        ],
    )
    def test_to_epoch_seconds(self, value: Any, expected: int) -> None:
        assert _to_epoch_seconds(value) == expected

    def test_naive_datetime_treated_as_utc(self) -> None:
        assert _to_epoch_seconds(datetime(2023, 11, 14, 22, 13, 20)) == 1700000000


class TestOffsetFromUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://api.sendgrid.com/v3/suppression/bounces?limit=500&offset=500", 500),
            ("https://api.sendgrid.com/v3/suppression/bounces?limit=500", 0),
            ("https://api.sendgrid.com/v3/suppression/bounces", 0),
        ],
    )
    def test_offset_from_url(self, url: str, expected: int) -> None:
        assert _offset_from_url(url) == expected


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"email": f"a{i}@x.com", "created": i} for i in range(500)]
        page2 = [{"email": "b@x.com", "created": 1}]
        params, _urls = _wire(session, [_response(page1), _response(page2)])

        manager = _make_manager()
        rows = _rows(_source("bounces", manager))

        assert rows == [*page1, *page2]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 500
        assert params[1]["offset"] == 500
        # Checkpoint saved once (after the full first page); the terminal short page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SendGridResumeConfig(offset=500)
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"email": "a@x.com"}, {"email": "b@x.com"}])])

        manager = _make_manager()
        rows = _rows(_source("bounces", manager))

        assert [r["email"] for r in rows] == ["a@x.com", "b@x.com"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"email": "b@x.com"}])])

        manager = _make_manager(SendGridResumeConfig(offset=500))
        _rows(_source("bounces", manager))

        assert params[0]["offset"] == 500

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_legacy_next_url_state(self, MockSession) -> None:
        # Pre-migration saved states stored the offset inside a full URL under ``next_url``.
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"email": "b@x.com"}])])

        resume_url = "https://api.sendgrid.com/v3/suppression/bounces?limit=500&offset=500"
        manager = _make_manager(SendGridResumeConfig(next_url=resume_url))
        _rows(_source("bounces", manager))

        assert params[0]["offset"] == 500

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_start_time_in_initial_params(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"email": "b@x.com"}])])

        _rows(
            _source(
                "bounces",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="created",
            )
        )

        assert params[0]["start_time"] == 1700000000
        assert params[0]["offset"] == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_start_time_without_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"email": "b@x.com"}])])

        _rows(_source("bounces", _make_manager()))
        assert "start_time" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"unexpected": "dict"})])

        # A 200 body that isn't the expected bare array means the response shape changed — fail
        # loud instead of silently syncing 0 rows.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("bounces", _make_manager()))


class TestMetadataPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_metadata_next(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = "https://api.sendgrid.com/v3/marketing/lists?page_token=tok&page_size=100"
        page1 = {"result": [{"id": 1}], "_metadata": {"next": next_url}}
        page2 = {"result": [{"id": 2}], "_metadata": {}}
        params, urls = _wire(session, [_response(page1), _response(page2)])

        manager = _make_manager()
        rows = _rows(_source("marketing_lists", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert params[0]["page_size"] == 100
        assert urls[1] == next_url
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SendGridResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_templates_sends_generations_param(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response({"result": [{"id": 1}], "_metadata": {}})])

        _rows(_source("templates", _make_manager()))
        assert params[0]["generations"] == "legacy,dynamic"
        assert params[0]["page_size"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_result_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"_metadata": {}})])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("marketing_lists", _make_manager()))


class TestOffHostGuard:
    @pytest.mark.parametrize(
        "off_host_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.example.com/v3/marketing/lists",
            "https://api.sendgrid.com.evil.com/v3/marketing/lists",
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_metadata_next_is_ignored(self, MockSession, off_host_url: str) -> None:
        session = MockSession.return_value
        page1 = {"result": [{"id": 1}], "_metadata": {"next": off_host_url}}
        _wire(session, [_response(page1)])

        manager = _make_manager()
        rows = _rows(_source("marketing_lists", manager))

        # The tampered next URL is dropped: yield the first page and stop without following it.
        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_resume_url_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(SendGridResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"))
        with pytest.raises(ValueError, match="unexpected URL"):
            _rows(_source("marketing_lists", manager))


class TestSinglePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_request_no_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        groups = [{"id": 1}, {"id": 2}]
        _wire(session, [_response(groups)])

        manager = _make_manager()
        rows = _rows(_source("unsubscribe_groups", manager))

        assert rows == groups
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_suppression_endpoint_partitioning_and_keys(self, MockSession) -> None:
        response = _source("bounces", _make_manager())
        assert response.name == "bounces"
        assert response.primary_keys == ["email"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]
        assert response.sort_mode == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_has_no_partitioning(self, MockSession) -> None:
        response = _source("marketing_lists", _make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestGetStatusCode:
    @pytest.mark.parametrize("status", [200, 401, 403, 404])
    def test_returns_status(self, status: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(SENDGRID_SESSION_PATCH, return_value=session):
            assert get_status_code("k", "/scopes") == status

    def test_returns_none_on_transport_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(SENDGRID_SESSION_PATCH, return_value=session):
            assert get_status_code("k", "/scopes") is None
