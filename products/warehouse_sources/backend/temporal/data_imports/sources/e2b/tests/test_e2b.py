import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b import (
    E2BResumeConfig,
    E2BRetryableError,
    e2b_source,
    validate_credentials,
)

# e2b builds its own tracked session and hands it to the RESTClient, so patch it in the e2b module.
E2B_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b.make_tracked_session"


def _response(body: Any, *, next_token: str | None = None, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    if next_token is not None:
        resp.headers["X-Next-Token"] = next_token
    return resp


def _make_manager(resume_state: E2BResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        # allowed_hosts pins requests to the base host, so the prepared URL must resolve there.
        prepared.url = "https://api.e2b.app/v2/sandboxes"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(manager: mock.MagicMock, endpoint: str = "sandboxes", api_key: str = "e2b_test"):
    return e2b_source(api_key=api_key, endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(E2B_SESSION_PATCH)
    def test_follows_next_token_header_across_pages(self, MockSession) -> None:
        # The paginator must chase the X-Next-Token header; stopping after page one silently drops data.
        session = MockSession.return_value
        params = _wire(
            session,
            [_response([{"sandboxID": "a"}, {"sandboxID": "b"}], next_token="t1"), _response([{"sandboxID": "c"}])],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"sandboxID": "a"}, {"sandboxID": "b"}, {"sandboxID": "c"}]
        # First page requested with no cursor, second page with the header token; limit ridden every page.
        assert params[0].get("nextToken") is None
        assert params[0]["limit"] == 100
        assert params[1]["nextToken"] == "t1"

    @mock.patch(E2B_SESSION_PATCH)
    def test_terminates_when_token_repeats(self, MockSession) -> None:
        # An endpoint that echoes the same cursor instead of dropping it must not loop forever.
        session = MockSession.return_value
        params = _wire(
            session,
            [_response([{"sandboxID": "a"}], next_token="same"), _response([{"sandboxID": "b"}], next_token="same")],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"sandboxID": "a"}, {"sandboxID": "b"}]
        assert params[0].get("nextToken") is None
        assert params[1]["nextToken"] == "same"
        assert session.send.call_count == 2

    @mock.patch(E2B_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        # A resumed run must start from the persisted cursor, not re-page from the beginning.
        session = MockSession.return_value
        params = _wire(session, [_response([{"sandboxID": "x"}])])

        rows = _rows(_source(_make_manager(E2BResumeConfig(next_token="resume_tok"))))

        assert rows == [{"sandboxID": "x"}]
        assert params[0]["nextToken"] == "resume_tok"

    @mock.patch(E2B_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"sandboxID": "a"}, {"sandboxID": "b"}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"sandboxID": "a"}, {"sandboxID": "b"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(E2B_SESSION_PATCH)
    def test_non_list_response_fails_loudly(self, MockSession) -> None:
        # E2B list endpoints return a bare JSON array; a wrapped/error object on a 200 is a response-shape
        # change. data_selector_required makes it fail loud rather than syncing the object as a row.
        session = MockSession.return_value
        _wire(session, [_response({"code": 500, "message": "boom"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source(_make_manager()))

    @mock.patch(E2B_SESSION_PATCH)
    def test_drops_sensitive_metadata_before_ingesting(self, MockSession) -> None:
        # E2B lets users stash secrets in sandbox metadata; writing it to the table would leak them to
        # anyone with table read access, so it must be stripped before ingesting. Other fields survive.
        session = MockSession.return_value
        _wire(session, [_response([{"sandboxID": "a", "metadata": {"API_KEY": "sk-secret"}, "state": "running"}])])

        rows = _rows(_source(_make_manager()))

        assert rows == [{"sandboxID": "a", "state": "running"}]

    @mock.patch(E2B_SESSION_PATCH)
    def test_saves_next_page_cursor_after_yielding_a_page(self, MockSession) -> None:
        # Save-after-yield with the NEXT page's token is what makes resume re-yield (not skip) the last
        # page on a crash, and only while a page remains (the final short page saves nothing).
        session = MockSession.return_value
        _wire(session, [_response([{"sandboxID": "a"}], next_token="t1"), _response([{"sandboxID": "last"}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"sandboxID": "a"}, {"sandboxID": "last"}]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == E2BResumeConfig(next_token="t1")

    @mock.patch(E2B_SESSION_PATCH)
    def test_builds_a_redacted_redirect_pinned_uncaptured_session(self, MockSession) -> None:
        # The sync session carries the X-API-Key header the scrubber can't see, so it must redact the
        # key and refuse redirects; capture=False keeps secret-bearing sandbox metadata out of sample
        # storage, which the row-level scrub can't do (it only runs after capture).
        _wire(MockSession.return_value, [_response([])])

        _rows(_source(_make_manager(), api_key="e2b_secret"))

        assert MockSession.call_args.kwargs == {
            "redact_values": ("e2b_secret",),
            "allow_redirects": False,
            "capture": False,
        }

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch(E2B_SESSION_PATCH)
    def test_retryable_status_codes_retry_then_succeed(self, _name: str, status: int, MockSession) -> None:
        # A rate limit or 5xx is transient — the framework transport must retry rather than fail the sync.
        session = MockSession.return_value
        _wire(session, [_response(None, status=status), _response([{"sandboxID": "a"}])])

        with mock.patch.object(RESTClient._send_request.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            rows = _rows(_source(_make_manager()))

        assert rows == [{"sandboxID": "a"}]
        assert session.send.call_count == 2


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(E2B_SESSION_PATCH)
    def test_status_code_maps_to_validity(self, _name: str, status: int, expected: bool, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status)

        assert validate_credentials("e2b_test") is expected
        # The key rides in the X-API-Key header, which the generic scrubber's denylist doesn't cover, so
        # the probe must redact it, pin redirects off to stop it replaying elsewhere, and disable capture
        # so the sandbox response body never reaches sample storage.
        assert MockSession.call_args.kwargs == {
            "redact_values": ("e2b_test",),
            "allow_redirects": False,
            "capture": False,
        }

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch(E2B_SESSION_PATCH)
    def test_transient_status_raises_rather_than_reporting_invalid(self, _name: str, status: int, MockSession) -> None:
        # A rate limit or 5xx says nothing about the key; mapping it to "invalid" sends the user the wrong way.
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status)

        with pytest.raises(E2BRetryableError):
            validate_credentials("e2b_test")

    @mock.patch(E2B_SESSION_PATCH)
    def test_network_error_is_treated_as_transient(self, MockSession) -> None:
        # A connection failure is transient — it must surface as a retryable error, not a False "invalid key".
        MockSession.return_value.get.side_effect = Exception("connection reset")

        with pytest.raises(E2BRetryableError):
            validate_credentials("e2b_test")


class TestSourceResponsePartitioning:
    @parameterized.expand(
        [
            ("sandboxes", ["sandboxID"], "startedAt"),
            ("templates", ["templateID"], "createdAt"),
            # Snapshots carry no timestamp — a partition key would have to be an unstable field.
            ("snapshots", ["snapshotID"], None),
        ]
    )
    def test_primary_keys_and_partitioning_per_endpoint(
        self, endpoint: str, expected_pks: list[str], expected_partition: str | None
    ) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        if expected_partition is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"


@pytest.mark.parametrize("endpoint", ["sandboxes", "templates", "snapshots"])
def test_every_endpoint_builds_a_source_response(endpoint: str) -> None:
    response = _source(_make_manager(), endpoint=endpoint)
    assert response.name == endpoint
    assert callable(response.items)
