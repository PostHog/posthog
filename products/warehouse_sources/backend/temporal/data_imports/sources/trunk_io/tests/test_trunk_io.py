import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Request, RequestException, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.settings import (
    FAILING_TESTS_DEFAULT_LOOKBACK_DAYS,
    FAILING_TESTS_WINDOW_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.trunk_io import (
    TrunkIoResumeConfig,
    TrunkPageQueryPaginator,
    TrunkRepo,
    failing_tests,
    quarantined_tests,
    unhealthy_tests,
    validate_credentials,
)

REPO = TrunkRepo(host="github.com", owner="my-org", name="my-repo")
MAKE_SESSION_TARGET = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_redirect_response(location: str, status_code: int = 302) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Location"] = location
    resp._content = b""
    return resp


def _page(next_page_token: str = "") -> dict[str, Any]:
    return {
        "total_rows": 1,
        "total_pages": 1,
        "next_page_token": next_page_token,
        "prev_page_token": "",
        "last_page_token": "",
        "page_index": 0,
    }


class TestTrunkPageQueryPaginator:
    def test_init_request_seeds_page_query(self) -> None:
        paginator = TrunkPageQueryPaginator(page_size=50, page_token="")
        request = Request(method="POST", url="https://api.trunk.io/v1/flaky-tests/list-quarantined-tests")
        paginator.init_request(request)
        assert request.json["page_query"] == {"page_size": 50, "page_token": ""}

    @parameterized.expand(
        [
            ("has_next", "next-token", True),
            ("empty_string_token", "", False),
            ("missing_page", None, False),
        ]
    )
    def test_update_state(self, _label: str, next_token: Optional[str], expected_has_next: bool) -> None:
        paginator = TrunkPageQueryPaginator()
        response = MagicMock()
        response.json.return_value = {"page": _page(next_token)} if next_token is not None else {}
        paginator.update_state(response)

        assert paginator.has_next_page is expected_has_next
        if expected_has_next:
            assert paginator.page_token == next_token

    def test_get_resume_state_round_trip(self) -> None:
        paginator = TrunkPageQueryPaginator()
        response = MagicMock()
        response.json.return_value = {"page": _page("cursor-1")}
        paginator.update_state(response)

        state = paginator.get_resume_state()
        assert state == {"page_token": "cursor-1"}

        resumed = TrunkPageQueryPaginator()
        resumed.set_resume_state(state)
        assert resumed.page_token == "cursor-1"
        assert resumed.has_next_page is True

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = TrunkPageQueryPaginator()
        response = MagicMock()
        response.json.return_value = {"page": _page("")}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None

    def test_set_resume_state_ignores_missing_token(self) -> None:
        paginator = TrunkPageQueryPaginator()
        paginator.set_resume_state({})
        assert paginator.page_token == ""


def _drive_session(responses: list[Response]) -> tuple[Any, list[dict[str, Any]]]:
    """Patch the tracked session so `RESTClient.paginate` runs against canned responses.

    Returns the mock session and the list of JSON bodies sent (captured at send-time, since
    the paginator mutates the same Request object in place between pages).
    """
    sent_bodies: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_bodies.append(json.loads(json.dumps(request.json)))
        return next(response_iter)

    patcher = patch(MAKE_SESSION_TARGET)
    mock_make_session = patcher.start()
    mock_session = mock_make_session.return_value
    mock_session.headers = {}
    mock_session.prepare_request.side_effect = lambda req: req
    mock_session.send.side_effect = fake_send
    return patcher, sent_bodies


class TestUnhealthyTests:
    def test_fresh_run_walks_both_statuses(self) -> None:
        patcher, sent_bodies = _drive_session(
            [
                _make_http_response({"tests": [{"id": "flaky-1"}], "page": _page("")}),
                _make_http_response({"tests": [{"id": "broken-1"}], "page": _page("")}),
            ]
        )
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            pages = list(unhealthy_tests("token", REPO, "my-org", manager))
        finally:
            patcher.stop()

        assert pages == [[{"id": "flaky-1"}], [{"id": "broken-1"}]]
        assert [body["status"] for body in sent_bodies] == ["FLAKY", "BROKEN"]
        manager.clear_state.assert_called_once()

    def test_resume_skips_completed_status(self) -> None:
        patcher, sent_bodies = _drive_session(
            [
                _make_http_response({"tests": [{"id": "broken-resumed"}], "page": _page("")}),
            ]
        )
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = True
            manager.load_state.return_value = TrunkIoResumeConfig(status="BROKEN", page_token="")

            pages = list(unhealthy_tests("token", REPO, "my-org", manager))
        finally:
            patcher.stop()

        assert pages == [[{"id": "broken-resumed"}]]
        assert [body["status"] for body in sent_bodies] == ["BROKEN"]

    def test_resume_seeds_page_token_mid_status(self) -> None:
        patcher, sent_bodies = _drive_session(
            [
                _make_http_response({"tests": [{"id": "flaky-2"}], "page": _page("")}),
                _make_http_response({"tests": [{"id": "broken-1"}], "page": _page("")}),
            ]
        )
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = True
            manager.load_state.return_value = TrunkIoResumeConfig(status="FLAKY", page_token="cursor-mid")

            list(unhealthy_tests("token", REPO, "my-org", manager))
        finally:
            patcher.stop()

        assert sent_bodies[0]["page_query"]["page_token"] == "cursor-mid"
        # Second status always starts fresh regardless of the seeded token.
        assert sent_bodies[1]["page_query"]["page_token"] == ""

    def test_saves_state_after_each_non_terminal_page(self) -> None:
        patcher, _ = _drive_session(
            [
                _make_http_response({"tests": [{"id": "flaky-1"}], "page": _page("cursor-1")}),
                _make_http_response({"tests": [{"id": "flaky-2"}], "page": _page("")}),
                _make_http_response({"tests": [{"id": "broken-1"}], "page": _page("")}),
            ]
        )
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            list(unhealthy_tests("token", REPO, "my-org", manager))
        finally:
            patcher.stop()

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [TrunkIoResumeConfig(status="FLAKY", page_token="cursor-1")]


class TestQuarantinedTests:
    def test_fresh_run_sends_no_seeded_token(self) -> None:
        patcher, sent_bodies = _drive_session(
            [_make_http_response({"quarantined_tests": [{"name": "test_a"}], "page": _page("")})]
        )
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            pages = list(quarantined_tests("token", REPO, "my-org", manager))
        finally:
            patcher.stop()

        assert pages == [[{"name": "test_a"}]]
        assert sent_bodies[0]["page_query"]["page_token"] == ""
        assert "status" not in sent_bodies[0]
        manager.clear_state.assert_called_once()

    def test_resume_seeds_saved_page_token(self) -> None:
        patcher, sent_bodies = _drive_session(
            [_make_http_response({"quarantined_tests": [{"name": "test_b"}], "page": _page("")})]
        )
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = True
            manager.load_state.return_value = TrunkIoResumeConfig(page_token="cursor-resumed")

            list(quarantined_tests("token", REPO, "my-org", manager))
        finally:
            patcher.stop()

        assert sent_bodies[0]["page_query"]["page_token"] == "cursor-resumed"

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        patcher, _ = _drive_session([_make_http_response({"quarantined_tests": [], "page": _page("")})])
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            list(quarantined_tests("token", REPO, "my-org", manager))
        finally:
            patcher.stop()

        manager.load_state.assert_not_called()


class TestFailingTests:
    @freeze_time("2024-06-15T00:00:00Z")
    def test_fresh_run_defaults_to_lookback_window(self) -> None:
        # The 30-day default lookback is walked in 7-day windows, so a fresh run issues
        # several requests before reaching "now" — only the first row matters here.
        responses = [_make_http_response({"tests": [{"id": "f-1"}], "page": _page("")})] + [
            _make_http_response({"tests": [], "page": _page("")}) for _ in range(9)
        ]
        patcher, sent_bodies = _drive_session(responses)
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            pages = list(
                failing_tests(
                    "token",
                    REPO,
                    "my-org",
                    manager,
                    should_use_incremental_field=False,
                    db_incremental_field_last_value=None,
                )
            )
        finally:
            patcher.stop()

        now = datetime(2024, 6, 15, tzinfo=UTC)
        expected_start = now - timedelta(days=FAILING_TESTS_DEFAULT_LOOKBACK_DAYS)
        assert sent_bodies[0]["start_time"] == expected_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Row gets a `synced_through` cursor stamped on it for incremental watermarking.
        assert pages[0][0]["synced_through"] == sent_bodies[0]["end_time"]

    @freeze_time("2024-06-15T00:00:00Z")
    def test_incremental_run_starts_from_last_value(self) -> None:
        # 2024-06-01 -> 2024-06-15 is 14 days, walked in two 7-day windows.
        last_value = "2024-06-01T00:00:00Z"
        responses = [_make_http_response({"tests": [], "page": _page("")}) for _ in range(2)]
        patcher, sent_bodies = _drive_session(responses)
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            list(
                failing_tests(
                    "token",
                    REPO,
                    "my-org",
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )
        finally:
            patcher.stop()

        assert sent_bodies[0]["start_time"] == last_value

    @freeze_time("2024-06-15T00:00:00Z")
    def test_window_capped_at_seven_days(self) -> None:
        last_value = "2024-01-01T00:00:00Z"
        patcher, sent_bodies = _drive_session(
            [_make_http_response({"tests": [], "page": _page("")}) for _ in range(30)]
        )
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            list(
                failing_tests(
                    "token",
                    REPO,
                    "my-org",
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )
        finally:
            patcher.stop()

        first_start = datetime.strptime(sent_bodies[0]["start_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        first_end = datetime.strptime(sent_bodies[0]["end_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert (first_end - first_start).days == FAILING_TESTS_WINDOW_DAYS

    @freeze_time("2024-06-15T00:00:00Z")
    def test_resume_seeds_window_and_page_token(self) -> None:
        patcher, sent_bodies = _drive_session([_make_http_response({"tests": [{"id": "f-2"}], "page": _page("")})])
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = True
            manager.load_state.return_value = TrunkIoResumeConfig(
                window_start="2024-06-10T00:00:00+00:00", page_token="cursor-mid"
            )

            list(
                failing_tests(
                    "token",
                    REPO,
                    "my-org",
                    manager,
                    should_use_incremental_field=False,
                    db_incremental_field_last_value=None,
                )
            )
        finally:
            patcher.stop()

        assert sent_bodies[0]["start_time"] == "2024-06-10T00:00:00Z"
        assert sent_bodies[0]["page_query"]["page_token"] == "cursor-mid"

    @freeze_time("2024-06-15T00:00:00Z")
    def test_terminates_once_window_reaches_now(self) -> None:
        # Seed exactly at "now" so the walk loop must not fire a single request.
        patcher, sent_bodies = _drive_session([])
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = True
            manager.load_state.return_value = TrunkIoResumeConfig(window_start="2024-06-15T00:00:00+00:00")

            pages = list(
                failing_tests(
                    "token",
                    REPO,
                    "my-org",
                    manager,
                    should_use_incremental_field=False,
                    db_incremental_field_last_value=None,
                )
            )
        finally:
            patcher.stop()

        assert pages == []
        assert sent_bodies == []
        manager.clear_state.assert_called_once()


class TestClientRedirectHandling:
    def test_redirect_is_refused_without_replaying_token(self) -> None:
        # A 30x from the API host must not be followed — `x-api-token` is a nonstandard header
        # `requests` wouldn't strip off-origin, so following the redirect would replay the token.
        sent_bodies: list[dict[str, Any]] = []

        def fake_send(request: Any, *_args: Any, **kwargs: Any) -> Response:
            sent_bodies.append(json.loads(json.dumps(request.json)))
            # The client must not ask the transport to follow redirects itself.
            assert kwargs.get("allow_redirects") is False
            return _make_redirect_response("https://evil.example.com/steal")

        patcher = patch(MAKE_SESSION_TARGET)
        mock_make_session = patcher.start()
        mock_session = mock_make_session.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send
        try:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            with pytest.raises(ValueError, match="[Rr]edirect"):
                list(quarantined_tests("token", REPO, "my-org", manager))
        finally:
            patcher.stop()

        # Exactly one request went out (to the API host); the redirect target was never called.
        assert len(sent_bodies) == 1


class TestValidateCredentials:
    def test_credential_check_disables_redirects(self) -> None:
        # Redirects off keeps the token from leaking to a redirect target during validation.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.trunk_io.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.post.return_value = _make_http_response({}, status_code=200)

            validate_credentials("token", "my-org", REPO)

        assert mock_make_session.call_args.kwargs["allow_redirects"] is False

    @parameterized.expand(
        [
            (200, True, None),
            (
                401,
                False,
                "Trunk.io authentication failed. Check your API token, organization slug, and repository details.",
            ),
            (500, False, "Trunk.io API returned HTTP 500."),
        ]
    )
    def test_status_code_mapping(self, status_code: int, expected_ok: bool, expected_error: Optional[str]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.trunk_io.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.post.return_value = _make_http_response({}, status_code=status_code)

            ok, error = validate_credentials("token", "my-org", REPO)

        assert ok is expected_ok
        assert error == expected_error

    def test_network_error_is_reported(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.trunk_io.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.post.side_effect = RequestException("boom")

            ok, error = validate_credentials("token", "my-org", REPO)

        assert ok is False
        assert error is not None and "boom" in error
