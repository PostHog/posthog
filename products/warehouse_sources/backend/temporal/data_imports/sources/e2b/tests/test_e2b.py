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
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.settings import ENDPOINTS

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
    def test_follows_next_token_header_across_pages(self, MockSession) -> None:
        # The paginator must chase the X-Next-Token header; stopping after page one silently drops data.
        session = MockSession.return_value
        calls = _wire(
            session,
            [_response([{"sandboxID": "a"}, {"sandboxID": "b"}], next_token="t1"), _response([{"sandboxID": "c"}])],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"sandboxID": "a"}, {"sandboxID": "b"}, {"sandboxID": "c"}]
        # First page requested with no cursor, second page with the header token; limit ridden every page.
        assert calls[0]["params"].get("nextToken") is None
        assert calls[0]["params"]["limit"] == 100
        assert calls[1]["params"]["nextToken"] == "t1"

    @mock.patch(E2B_SESSION_PATCH)
    def test_terminates_when_token_repeats(self, MockSession) -> None:
        # An endpoint that echoes the same cursor instead of dropping it must not loop forever.
        session = MockSession.return_value
        calls = _wire(
            session,
            [_response([{"sandboxID": "a"}], next_token="same"), _response([{"sandboxID": "b"}], next_token="same")],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"sandboxID": "a"}, {"sandboxID": "b"}]
        assert calls[0]["params"].get("nextToken") is None
        assert calls[1]["params"]["nextToken"] == "same"
        assert session.send.call_count == 2

    @mock.patch(E2B_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        # A resumed run must start from the persisted cursor, not re-page from the beginning.
        session = MockSession.return_value
        calls = _wire(session, [_response([{"sandboxID": "x"}])])

        rows = _rows(_source(_make_manager(E2BResumeConfig(next_token="resume_tok"))))

        assert rows == [{"sandboxID": "x"}]
        assert calls[0]["params"]["nextToken"] == "resume_tok"

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


@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_every_endpoint_builds_a_source_response(endpoint: str) -> None:
    response = _source(_make_manager(), endpoint=endpoint, e2b_team_id="prj_1")
    assert response.name == endpoint
    assert callable(response.items)


class TestFanout:
    @mock.patch(E2B_SESSION_PATCH)
    def test_sandbox_metrics_fans_out_per_sandbox_and_stamps_the_sandbox_id(self, MockSession) -> None:
        # A SandboxMetric row carries no sandbox id, so without the parent injection every row in the
        # table would be unattributable — and the primary key would collide across sandboxes.
        session = MockSession.return_value
        calls = _wire(
            session,
            [
                _response([{"sandboxID": "s1"}, {"sandboxID": "s2"}]),
                _response([{"timestampUnix": 10, "cpuUsedPct": 1.5}]),
                _response([{"timestampUnix": 11, "cpuUsedPct": 2.5}]),
            ],
        )

        rows = _rows(_source(_make_manager(), endpoint="sandbox_metrics"))

        assert rows == [
            {"timestampUnix": 10, "cpuUsedPct": 1.5, "sandboxID": "s1"},
            {"timestampUnix": 11, "cpuUsedPct": 2.5, "sandboxID": "s2"},
        ]
        assert [call["url"] for call in calls] == [
            "https://api.e2b.app/v2/sandboxes",
            "https://api.e2b.app/sandboxes/s1/metrics",
            "https://api.e2b.app/sandboxes/s2/metrics",
        ]
        # The parent keeps its documented page size; the child documents no limit param, so sending
        # one risks a strict validator rejecting the request.
        assert calls[0]["params"]["limit"] == 100
        assert "limit" not in calls[1]["params"]

    @mock.patch(E2B_SESSION_PATCH)
    def test_template_builds_reads_the_builds_key_and_stamps_the_template_id(self, MockSession) -> None:
        # /templates/{templateID} answers with the template object, not a build array, so a missing
        # data_selector would sync one row holding the whole object.
        session = MockSession.return_value
        calls = _wire(
            session,
            [
                _response([{"templateID": "t1"}]),
                _response({"templateID": "t1", "builds": [{"buildID": "b1", "status": "ready"}]}),
            ],
        )

        rows = _rows(_source(_make_manager(), endpoint="template_builds"))

        assert rows == [{"buildID": "b1", "status": "ready", "templateID": "t1"}]
        assert calls[1]["url"] == "https://api.e2b.app/templates/t1"

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

    @mock.patch(E2B_SESSION_PATCH)
    def test_fanout_resume_skips_parents_already_completed(self, MockSession) -> None:
        session = MockSession.return_value
        calls = _wire(
            session,
            [
                _response([{"templateID": "t1"}, {"templateID": "t2"}]),
                _response({"builds": [{"buildID": "b2"}]}),
            ],
        )

        resume = E2BResumeConfig(fanout={"completed": ["/templates/t1"], "current": None, "child_state": None})
        rows = _rows(_source(_make_manager(resume), endpoint="template_builds"))

        assert rows == [{"buildID": "b2", "templateID": "t2"}]
        assert [call["url"] for call in calls] == [
            "https://api.e2b.app/v2/templates",
            "https://api.e2b.app/templates/t2",
        ]


class TestLatestSandboxMetrics:
    @mock.patch(E2B_SESSION_PATCH)
    def test_batches_a_page_of_sandboxes_into_one_request_and_keys_rows_by_sandbox(self, MockSession) -> None:
        # The endpoint takes up to 100 ids per call and answers with a sandboxID -> metric map, so the
        # id only exists as a map key. One request per page is the whole point of this table.
        session = MockSession.return_value
        calls = _wire(
            session,
            [
                _response([{"sandboxID": "s1"}, {"sandboxID": "s2"}]),
                _response({"sandboxes": {"s1": {"cpuUsedPct": 1.0}, "s2": {"cpuUsedPct": 2.0}}}),
            ],
        )

        rows = _rows(_source(_make_manager(), endpoint="sandbox_metrics_latest"))

        assert rows == [
            {"cpuUsedPct": 1.0, "sandboxID": "s1"},
            {"cpuUsedPct": 2.0, "sandboxID": "s2"},
        ]
        assert calls[1]["url"] == "https://api.e2b.app/sandboxes/metrics"
        assert calls[1]["params"]["sandbox_ids"] == "s1,s2"

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
    def test_a_page_with_no_sandboxes_makes_no_metrics_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source(_make_manager(), endpoint="sandbox_metrics_latest")) == []
        assert session.send.call_count == 1

    @mock.patch(E2B_SESSION_PATCH)
    def test_missing_sandboxes_key_fails_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"sandboxID": "s1"}]), _response({"error": "nope"})])

        with pytest.raises(ValueError, match="data_selector"):
            _rows(_source(_make_manager(), endpoint="sandbox_metrics_latest"))


class TestTeamMetrics:
    @mock.patch(E2B_SESSION_PATCH)
    def test_puts_the_team_id_in_the_path_and_sends_no_page_size(self, MockSession) -> None:
        # E2B takes the team in the path even though the API key already identifies it, and the
        # endpoint documents no pagination — a stray limit/nextToken would be an undocumented param.
        session = MockSession.return_value
        calls = _wire(session, [_response([{"timestampUnix": 5, "concurrentSandboxes": 3}])])

        rows = _rows(_source(_make_manager(), endpoint="team_metrics", e2b_team_id=" prj_abc "))

        assert rows == [{"timestampUnix": 5, "concurrentSandboxes": 3}]
        assert calls[0]["url"] == "https://api.e2b.app/teams/prj_abc/metrics"
        assert calls[0]["params"] == {}
        assert session.send.call_count == 1

    @parameterized.expand([("missing", None), ("blank", "   "), ("path_traversal", "../admin/teams")])
    def test_an_unusable_team_id_fails_before_any_request(self, _name: str, team_id: str | None) -> None:
        # The value lands in a request path, so anything but an opaque identifier must be refused
        # rather than interpolated.
        with pytest.raises(E2BConfigurationError):
            _source(_make_manager(), endpoint="team_metrics", e2b_team_id=team_id)
