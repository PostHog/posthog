from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.klaus import (
    DEFAULT_FROM_DATE,
    MAX_RETRY_WAIT_SECONDS,
    KlausResumeConfig,
    KlausRetryableError,
    _build_params,
    _format_datetime,
    _retry_wait,
    get_base_url,
    get_rows,
    klaus_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.settings import KLAUS_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.klaus.klaus"


def _response(body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.is_redirect = status in (301, 302, 303, 307, 308)
    response.json.return_value = body
    response.headers = headers or {}
    response.text = str(body)
    return response


def _manager(resume: KlausResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _drive(
    endpoint: str,
    responses: list[MagicMock],
    manager: MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], MagicMock, MagicMock]:
    manager = manager if manager is not None else _manager()
    with patch(f"{MODULE}.make_tracked_session") as MockSession:
        session = MockSession.return_value
        session.get.side_effect = responses
        batches = list(
            get_rows(
                subdomain="acme",
                api_token="test-token",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )
    return batches, session, manager


def _sent(session: MagicMock) -> list[tuple[str, dict[str, Any]]]:
    return [(call.args[0], dict(call.kwargs.get("params") or {})) for call in session.get.call_args_list]


class TestGetBaseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("acme", "https://acme.zendesk.com/qa"),
            ("  ACME  ", "https://acme.zendesk.com/qa"),
            ("acme.zendesk.com", "https://acme.zendesk.com/qa"),
            ("https://acme.zendesk.com/", "https://acme.zendesk.com/qa"),
            ("my-team2", "https://my-team2.zendesk.com/qa"),
        ],
    )
    def test_normalizes_valid_input(self, raw: str, expected: str) -> None:
        assert get_base_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "evil.com/acme",
            "acme.evil.com",
            "acme zendesk",
            "-acme",
            "acme?x=1",
        ],
    )
    def test_rejects_host_escapes(self, raw: str) -> None:
        # A subdomain with dots, slashes, or other URL syntax could splice a
        # different host into the request URL and receive the bearer token.
        with pytest.raises(ValueError):
            get_base_url(raw)


class TestBuildParams:
    def test_required_from_date_defaults_on_full_refresh(self) -> None:
        params = _build_params(KLAUS_ENDPOINTS["reviews"], False, None)
        assert params == {"fromDate": _format_datetime(DEFAULT_FROM_DATE)}

    @pytest.mark.parametrize(
        "last_value",
        [
            datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            "2026-01-02T12:00:00Z",
            "2026-01-02T12:00:00+00:00",
        ],
    )
    def test_incremental_value_applies_overlap(self, last_value: Any) -> None:
        # The watermark is pulled back by the overlap window so an undocumented
        # exclusive fromDate boundary can't skip same-timestamp rows.
        params = _build_params(KLAUS_ENDPOINTS["reviews"], True, last_value)
        assert params == {"fromDate": "2026-01-02T11:00:00Z"}

    @pytest.mark.parametrize("endpoint", ["disputes", "users", "workspaces"])
    def test_full_refresh_endpoints_without_required_from_date_send_none(self, endpoint: str) -> None:
        assert _build_params(KLAUS_ENDPOINTS[endpoint], False, None) == {}


class TestPagination:
    def _page(self, items: list[dict[str, Any]], page: int | None, page_size: int, total: int | None = None) -> dict:
        pagination: dict[str, Any] = {"pageSize": page_size}
        if page is not None:
            pagination["page"] = page
        if total is not None:
            pagination["total"] = total
        return {"conversations": items, "pagination": pagination}

    def test_one_indexed_server_advances_from_echo(self) -> None:
        responses = [
            _response(self._page([{"externalId": "a"}, {"externalId": "b"}], page=1, page_size=2)),
            _response(self._page([{"externalId": "c"}], page=2, page_size=2)),
        ]
        batches, session, manager = _drive("reviews", responses)

        assert batches == [[{"externalId": "a"}, {"externalId": "b"}], [{"externalId": "c"}]]
        sent = _sent(session)
        # The first request omits `page` (indexing base unknown); the second follows
        # the server's echo.
        assert "page" not in sent[0][1]
        assert sent[1][1]["page"] == 2
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            KlausResumeConfig(next_page=2, workspace_id=None)
        ]

    def test_zero_indexed_server_advances_from_omitted_echo(self) -> None:
        # proto3 JSON omits zero values, so a 0-indexed first page arrives with no
        # `page` key in the pagination echo.
        responses = [
            _response(self._page([{"externalId": "a"}, {"externalId": "b"}], page=None, page_size=2)),
            _response(self._page([{"externalId": "c"}], page=1, page_size=2)),
        ]
        _, session, _ = _drive("reviews", responses)

        sent = _sent(session)
        assert "page" not in sent[0][1]
        assert sent[1][1]["page"] == 1

    def test_server_clamped_page_size_still_detects_full_pages(self) -> None:
        # We request pageSize=100 but the server clamps to 2 and says so in the echo;
        # a 2-item page must still count as full rather than terminating the sync.
        responses = [
            _response(self._page([{"externalId": "a"}, {"externalId": "b"}], page=1, page_size=2)),
            _response(self._page([], page=2, page_size=2)),
        ]
        batches, session, _ = _drive("reviews", responses)

        assert len(batches) == 1
        assert _sent(session)[0][1]["pageSize"] == 100

    def test_terminal_short_page_does_not_save_state(self) -> None:
        responses = [_response(self._page([{"externalId": "a"}], page=1, page_size=2))]
        batches, _, manager = _drive("reviews", responses)

        assert len(batches) == 1
        manager.save_state.assert_not_called()

    def test_empty_first_page_yields_nothing(self) -> None:
        responses = [_response(self._page([], page=1, page_size=2))]
        batches, _, manager = _drive("reviews", responses)

        assert batches == []
        manager.save_state.assert_not_called()

    def test_resume_requests_saved_page(self) -> None:
        manager = _manager(KlausResumeConfig(next_page=5, workspace_id=None))
        responses = [_response(self._page([{"externalId": "resumed"}], page=5, page_size=2))]
        _, session, _ = _drive("reviews", responses, manager=manager)

        assert _sent(session)[0][1]["page"] == 5

    def test_stuck_page_echo_raises_instead_of_looping(self) -> None:
        stuck = self._page([{"externalId": "a"}, {"externalId": "b"}], page=1, page_size=2)
        responses = [_response(stuck), _response(stuck)]

        with pytest.raises(Exception, match="did not advance"):
            _drive("reviews", responses)

    def test_incremental_from_date_sent_on_every_page(self) -> None:
        responses = [
            _response(self._page([{"externalId": "a"}, {"externalId": "b"}], page=1, page_size=2)),
            _response(self._page([], page=2, page_size=2)),
        ]
        _, session, _ = _drive(
            "reviews",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
        )

        for _url, params in _sent(session):
            assert params["fromDate"] == "2026-01-02T11:00:00Z"


class TestNonPaginatedEndpoints:
    def test_users_is_a_single_unpaginated_request(self) -> None:
        responses = [_response({"users": [{"id": "1", "name": "Alice"}]})]
        batches, session, manager = _drive("users", responses)

        assert batches == [[{"id": "1", "name": "Alice"}]]
        sent = _sent(session)
        assert len(sent) == 1
        assert "page" not in sent[0][1]
        assert "pageSize" not in sent[0][1]
        manager.save_state.assert_not_called()


class TestFanOut:
    def test_fans_out_over_workspaces_and_injects_workspace_id(self) -> None:
        responses = [
            _response({"workspaces": [{"id": 1, "name": "Support"}, {"id": 2, "name": "Sales"}]}),
            _response({"data": [{"id": "10"}]}),
            _response({"data": [{"id": "10"}]}),
        ]
        batches, session, manager = _drive("scorecards", responses)

        urls = [url for url, _ in _sent(session)]
        assert urls == [
            "https://acme.zendesk.com/qa/api/export/workspaces",
            "https://acme.zendesk.com/qa/api/export/workspace/1/scorecards",
            "https://acme.zendesk.com/qa/api/export/workspace/2/scorecards",
        ]
        # The injected workspace id keeps the composite primary key unique table-wide
        # when the same scorecard id exists in more than one workspace.
        assert batches == [[{"id": "10", "workspace_id": "1"}], [{"id": "10", "workspace_id": "2"}]]
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            KlausResumeConfig(next_page=None, workspace_id="2")
        ]

    def test_resume_skips_completed_workspaces(self) -> None:
        manager = _manager(KlausResumeConfig(next_page=None, workspace_id="2"))
        responses = [
            _response({"workspaces": [{"id": 1}, {"id": 2}]}),
            _response({"data": [{"id": "10"}]}),
        ]
        batches, session, _ = _drive("scorecards", responses, manager=manager)

        urls = [url for url, _ in _sent(session)]
        assert urls == [
            "https://acme.zendesk.com/qa/api/export/workspaces",
            "https://acme.zendesk.com/qa/api/export/workspace/2/scorecards",
        ]
        assert batches == [[{"id": "10", "workspace_id": "2"}]]

    def test_deleted_bookmark_workspace_restarts_from_scratch(self) -> None:
        manager = _manager(KlausResumeConfig(next_page=3, workspace_id="99"))
        responses = [
            _response({"workspaces": [{"id": 1}]}),
            _response({"data": [{"id": "10"}]}),
        ]
        _, session, _ = _drive("scorecards", responses, manager=manager)

        sent = _sent(session)
        assert sent[1][0] == "https://acme.zendesk.com/qa/api/export/workspace/1/scorecards"
        assert "page" not in sent[1][1]

    def test_from_date_applies_to_workspace_requests_but_not_workspace_listing(self) -> None:
        responses = [
            _response({"workspaces": [{"id": 1}]}),
            _response({"calibrationSessions": [{"id": "s1"}], "pagination": {"page": 1, "pageSize": 100}}),
        ]
        _, session, _ = _drive("calibration_sessions", responses)

        sent = _sent(session)
        assert "fromDate" not in sent[0][1]
        assert sent[1][1]["fromDate"] == _format_datetime(DEFAULT_FROM_DATE)


class TestRetry:
    def test_429_is_retried_honoring_retry_after(self) -> None:
        responses = [
            _response({}, status=429, headers={"Retry-After": "30"}),
            _response({"users": [{"id": "1"}]}),
        ]
        with patch("time.sleep") as mock_sleep:
            batches, _, _ = _drive("users", responses)

        assert batches == [[{"id": "1"}]]
        assert mock_sleep.call_args.args[0] == 31.0

    def test_retry_wait_caps_excessive_retry_after(self) -> None:
        retry_state = MagicMock()
        retry_state.outcome.exception.return_value = KlausRetryableError("throttled", retry_after=100_000)
        assert _retry_wait(retry_state) == MAX_RETRY_WAIT_SECONDS


class TestSourceResponse:
    def test_reviews_response_shape(self) -> None:
        response = klaus_source("acme", "token", "reviews", MagicMock(), _manager())

        assert response.name == "reviews"
        # Conversation externalId is the helpdesk ticket id, only unique per workspace.
        assert response.primary_keys == ["workspaceId", "externalId"]
        # Response ordering is undocumented, so the watermark must only persist at
        # successful job end.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAtISO"]

    def test_unpartitioned_endpoint_has_no_partition_settings(self) -> None:
        response = klaus_source("acme", "token", "users", MagicMock(), _manager())

        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
            # A throttled probe still reached the account's API; the aggressive public
            # rate limit must not block source creation.
            (429, True),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(f"{MODULE}.make_tracked_session") as MockSession:
            MockSession.return_value.get.return_value = _response({}, status=status_code)

            valid, error = validate_credentials("acme", "test-token")

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_invalid_subdomain_fails_without_a_request(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as MockSession:
            valid, error = validate_credentials("acme.evil.com", "test-token")

        assert valid is False
        assert error is not None
        MockSession.assert_not_called()

    def test_network_error_returns_message(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            valid, error = validate_credentials("acme", "test-token")

        assert valid is False
        assert error == "boom"


class TestGetRowsIsLazy:
    def test_no_request_until_iterated(self) -> None:
        # source_for_pipeline builds the SourceResponse eagerly; the first HTTP call
        # must not happen until the pipeline starts consuming items.
        with patch(f"{MODULE}.make_tracked_session") as MockSession:
            response = klaus_source("acme", "token", "users", MagicMock(), _manager())
            MockSession.assert_not_called()

            MockSession.return_value.get.return_value = _response({"users": [{"id": "1"}]})
            items = response.items()
            assert isinstance(items, Iterator)
            assert list(items) == [[{"id": "1"}]]
