import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b import (
    E2BConfigurationError,
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
    """Wire a mock session and return a list capturing each request's url and params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    calls: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        calls.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        # allowed_hosts pins requests to the base host, and RESTClient already joined the path
        # against it, so echoing the request URL keeps the check honest.
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return calls


def _source(
    manager: mock.MagicMock,
    endpoint: str = "sandboxes",
    api_key: str = "e2b_test",
    e2b_team_id: str | None = None,
):
    return e2b_source(
        api_key=api_key,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        e2b_team_id=e2b_team_id,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(E2B_SESSION_PATCH)
    def test_non_list_response_fails_loudly(self, MockSession) -> None:
        # E2B list endpoints return a bare JSON array; a wrapped/error object on a 200 is a response-shape
        # change. data_selector_required makes it fail loud rather than syncing the object as a row.
        session = MockSession.return_value
        _wire(session, [_response({"code": 500, "message": "boom"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source(_make_manager()))

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

        ok, error = validate_credentials("e2b_test")
        assert ok is expected
        assert (error is None) is expected
        # The key rides in the X-API-Key header, which the generic scrubber's denylist doesn't cover, so
        # the probe must redact it, pin redirects off to stop it replaying elsewhere, and disable capture
        # so the sandbox response body never reaches sample storage.
        assert MockSession.call_args.kwargs == {
            "redact_values": ("e2b_test",),
            "allow_redirects": False,
            "capture": False,
        }

    # A key scoped to another team has to be re-scoped, not replaced, so a 403 must not read as a
    # revoked key and send someone off to generate another one that fails the same way.
    @parameterized.expand(
        [
            (401, "invalid or has been revoked"),
            (403, "does not have access to this data"),
        ]
    )
    @mock.patch(E2B_SESSION_PATCH)
    def test_a_revoked_key_and_a_key_without_access_read_differently(
        self, status: int, expected: str, MockSession
    ) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status)

        ok, error = validate_credentials("e2b_test")
        assert ok is False
        assert expected in (error or "")

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
            # A fan-out child aggregates rows from every parent, so the parent id has to be in the key.
            ("sandbox_metrics", ["sandboxID", "timestampUnix"], "timestamp"),
            ("template_builds", ["templateID", "buildID"], "createdAt"),
            # One row per sandbox, and its sample timestamp moves every sync, so it can't partition.
            ("sandbox_metrics_latest", ["sandboxID"], None),
            ("team_metrics", ["timestampUnix"], "timestamp"),
        ]
    )
    def test_primary_keys_and_partitioning_per_endpoint(
        self, endpoint: str, expected_pks: list[str], expected_partition: str | None
    ) -> None:
        response = _source(_make_manager(), endpoint=endpoint, e2b_team_id="prj_1")
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        if expected_partition is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"


class TestFanout:
    @mock.patch(E2B_SESSION_PATCH)
    def test_fanout_checkpoints_under_its_own_slot_and_resumes_from_it(self, MockSession) -> None:
        # Fan-out resume state is a completed-parents map, not a page cursor, so it must not be
        # written into next_token — replaying that against the API would be meaningless.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"templateID": "t1"}, {"templateID": "t2"}]),
                _response({"builds": [{"buildID": "b1"}]}),
                _response({"builds": [{"buildID": "b2"}]}),
            ],
        )

        manager = _make_manager()
        _rows(_source(manager, endpoint="template_builds"))

        saved = manager.save_state.call_args.args[0]
        assert saved.next_token is None
        assert saved.fanout is not None and sorted(saved.fanout["completed"]) == [
            "/templates/t1",
            "/templates/t2",
        ]


class TestLatestSandboxMetrics:
    @mock.patch(E2B_SESSION_PATCH)
    def test_walks_the_whole_sandbox_list_starting_from_a_resumed_cursor(self, MockSession) -> None:
        # The iterator drives the sandbox list itself, so it has to seed a resumed run from the saved
        # cursor and keep chasing the header token; stopping after one page leaves most sandboxes
        # with no metrics at all.
        session = MockSession.return_value
        calls = _wire(
            session,
            [
                _response([{"sandboxID": "s9"}], next_token="t2"),
                _response({"sandboxes": {"s9": {"cpuUsedPct": 9.0}}}),
                _response([{"sandboxID": "s10"}]),
                _response({"sandboxes": {"s10": {"cpuUsedPct": 10.0}}}),
            ],
        )

        rows = _rows(_source(_make_manager(E2BResumeConfig(next_token="tok")), endpoint="sandbox_metrics_latest"))

        assert rows == [{"cpuUsedPct": 9.0, "sandboxID": "s9"}, {"cpuUsedPct": 10.0, "sandboxID": "s10"}]
        assert calls[0]["params"]["nextToken"] == "tok"
        assert calls[2]["params"]["nextToken"] == "t2"

    @mock.patch(E2B_SESSION_PATCH)
    def test_missing_sandboxes_key_fails_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"sandboxID": "s1"}]), _response({"error": "nope"})])

        with pytest.raises(ValueError, match="data_selector"):
            _rows(_source(_make_manager(), endpoint="sandbox_metrics_latest"))


class TestTeamMetrics:
    @parameterized.expand([("missing", None), ("blank", "   "), ("path_traversal", "../admin/teams")])
    def test_an_unusable_team_id_fails_before_any_request(self, _name: str, team_id: str | None) -> None:
        # The value lands in a request path, so anything but an opaque identifier must be refused
        # rather than interpolated.
        with pytest.raises(E2BConfigurationError):
            _source(_make_manager(), endpoint="team_metrics", e2b_team_id=team_id)
