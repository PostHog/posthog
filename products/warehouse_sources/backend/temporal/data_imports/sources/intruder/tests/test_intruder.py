import json
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.intruder import (
    PAGE_SIZE,
    IntruderResumeConfig,
    intruder_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.settings import (
    INCREMENTAL_FIELDS,
    INTRUDER_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the intruder module.
INTRUDER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.intruder.intruder.make_tracked_session"
)
# Kill tenacity's backoff so retry classification tests don't actually sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"

BASE = "https://api.intruder.io/v1"


def _resp(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _redirect(location: str = "https://evil.com") -> Response:
    resp = Response()
    resp.status_code = 302
    resp.headers["Location"] = location
    return resp


def _norm(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    parts = urlsplit(url)
    return parts.path, tuple(sorted(parse_qsl(parts.query)))


def _make_manager(resume_state: IntruderResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses_by_url: dict[str, list[Response]]) -> list[dict[str, Any]]:
    """Wire a mock session that resolves each request by its fully-encoded URL.

    Values are per-URL queues so a URL can return different responses across retries/pages. Returns a
    list capturing each request's params snapshot at prepare time (the params dict is mutated in place
    across pages, so a post-run read would show only the final state).
    """
    session.headers = {}
    normalized: dict[tuple[str, tuple[tuple[str, str], ...]], list[Response]] = {
        _norm(url): list(queue) for url, queue in responses_by_url.items()
    }
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> Any:
        param_snapshots.append(dict(request.params or {}))
        return request.prepare()

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        queue = normalized.get(_norm(prepared.url))
        if queue is None:
            raise AssertionError(f"unexpected request url {prepared.url!r}")
        return queue.pop(0)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    endpoint: str, responses_by_url: dict[str, list[Response]], manager: mock.MagicMock
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        params = _wire(session, responses_by_url)
        rows = _rows(
            intruder_source(
                access_token="tok",
                endpoint=endpoint,
                team_id=1,
                job_id="job",
                resumable_source_manager=manager,
            )
        )
    return rows, params


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("targets", ["id"], None, None),
            ("scans", ["id"], "datetime", "created_at"),
            ("scan_schedules", ["id"], None, None),
            ("issues", ["id"], None, None),
            ("occurrences", ["issue_id", "id"], "datetime", "first_seen_at"),
            ("fixed_occurrences", ["id"], "datetime", "first_seen_at"),
            ("tags", ["name"], None, None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_and_partitioning(
        self,
        endpoint: str,
        expected_pks: list[str],
        expected_partition_mode: str | None,
        expected_partition_key: str | None,
        _MockSession: Any,
    ) -> None:
        response = intruder_source(
            access_token="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.partition_mode == expected_partition_mode
        assert response.partition_keys == ([expected_partition_key] if expected_partition_key else None)


class TestEndpointConfig:
    def test_occurrences_is_fan_out_with_composite_key(self) -> None:
        config = INTRUDER_ENDPOINTS["occurrences"]
        assert config.fan_out_over_issues is True
        # An occurrence id is only unique within its issue, so the key must include the parent issue.
        assert config.primary_keys == ["issue_id", "id"]

    def test_tags_keyed_by_name(self) -> None:
        # Tags are bare {name} objects with no numeric id, so name is the primary key.
        assert INTRUDER_ENDPOINTS["tags"].primary_keys == ["name"]

    def test_no_endpoint_advertises_incremental_fields(self) -> None:
        # Intruder exposes no server-side timestamp filter, so nothing advertises incremental fields.
        assert all(fields == [] for fields in INCREMENTAL_FIELDS.values())


class TestStandardPagination:
    def test_follows_next_url_until_exhausted(self) -> None:
        # A bug that dropped the `next` follow (or read the wrong key) would only return page one.
        responses = {
            f"{BASE}/targets/?limit={PAGE_SIZE}": [
                _resp({"results": [{"id": 1}, {"id": 2}], "next": f"{BASE}/targets/?limit={PAGE_SIZE}&offset=100"})
            ],
            f"{BASE}/targets/?limit={PAGE_SIZE}&offset=100": [_resp({"results": [{"id": 3}], "next": None})],
        }
        rows, params = _run("targets", responses, _make_manager())
        assert [r["id"] for r in rows] == [1, 2, 3]
        assert params[0]["limit"] == PAGE_SIZE

    def test_empty_first_page_terminates_without_saving(self) -> None:
        responses = {f"{BASE}/scans/?limit={PAGE_SIZE}": [_resp({"results": [], "next": None})]}
        manager = _make_manager()
        rows, _params = _run("scans", responses, manager)
        assert rows == []
        manager.save_state.assert_not_called()

    def test_saves_next_url_after_each_page_but_not_after_last(self) -> None:
        # State must be saved AFTER yielding a page and only when a next page remains, so a crash
        # re-yields the last page (merge dedupes) rather than skipping it. The final page saves nothing.
        responses = {
            f"{BASE}/targets/?limit={PAGE_SIZE}": [
                _resp({"results": [{"id": 1}], "next": f"{BASE}/targets/?limit={PAGE_SIZE}&offset=100"})
            ],
            f"{BASE}/targets/?limit={PAGE_SIZE}&offset=100": [_resp({"results": [{"id": 2}], "next": None})],
        }
        manager = _make_manager()
        _run("targets", responses, manager)
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [IntruderResumeConfig(next_url=f"{BASE}/targets/?limit={PAGE_SIZE}&offset=100")]

    def test_resumes_from_saved_next_url(self) -> None:
        # With saved state the first request must be the saved cursor, not the initial page.
        responses = {
            f"{BASE}/targets/?limit={PAGE_SIZE}&offset=100": [_resp({"results": [{"id": 2}], "next": None})],
        }
        state = IntruderResumeConfig(next_url=f"{BASE}/targets/?limit={PAGE_SIZE}&offset=100")
        rows, _params = _run("targets", responses, _make_manager(state))
        assert [r["id"] for r in rows] == [2]


class TestOccurrencesFanOut:
    def test_injects_parent_issue_id_into_every_row(self) -> None:
        # The occurrences response has no issue reference; without the injected issue_id the composite
        # primary key [issue_id, id] collapses to id and duplicate rows accumulate across issues.
        responses = {
            f"{BASE}/issues/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 10}, {"id": 20}], "next": None})],
            f"{BASE}/issues/10/occurrences/?limit={PAGE_SIZE}": [
                _resp({"results": [{"id": 1}, {"id": 2}], "next": None})
            ],
            f"{BASE}/issues/20/occurrences/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 3}], "next": None})],
        }
        rows, _params = _run("occurrences", responses, _make_manager())
        assert rows == [
            {"id": 1, "issue_id": 10},
            {"id": 2, "issue_id": 10},
            {"id": 3, "issue_id": 20},
        ]

    def test_follows_occurrence_pagination_within_an_issue(self) -> None:
        responses = {
            f"{BASE}/issues/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 10}], "next": None})],
            f"{BASE}/issues/10/occurrences/?limit={PAGE_SIZE}": [
                _resp({"results": [{"id": 1}], "next": f"{BASE}/issues/10/occurrences/?limit={PAGE_SIZE}&offset=100"})
            ],
            f"{BASE}/issues/10/occurrences/?limit={PAGE_SIZE}&offset=100": [
                _resp({"results": [{"id": 2}], "next": None})
            ],
        }
        rows, _params = _run("occurrences", responses, _make_manager())
        assert [r["id"] for r in rows] == [1, 2]

    def test_resume_skips_already_completed_issue(self) -> None:
        # An issue whose occurrences fully synced on the prior attempt is skipped on resume.
        responses = {
            f"{BASE}/issues/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 10}, {"id": 20}], "next": None})],
            f"{BASE}/issues/20/occurrences/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 3}], "next": None})],
        }
        state = IntruderResumeConfig(
            fanout_state={"completed": ["/issues/10/occurrences/"], "current": None, "child_state": None}
        )
        rows, _params = _run("occurrences", responses, _make_manager(state))
        assert rows == [{"id": 3, "issue_id": 20}]

    def test_resume_from_deleted_issue_restarts_from_first(self) -> None:
        # The in-progress issue from the saved state no longer exists — its checkpoint is ignored and
        # the surviving issues sync fresh (merge dedupes any re-pulled rows).
        responses = {
            f"{BASE}/issues/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 10}], "next": None})],
            f"{BASE}/issues/10/occurrences/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 1}], "next": None})],
        }
        state = IntruderResumeConfig(
            fanout_state={
                "completed": [],
                "current": "/issues/999/occurrences/",
                "child_state": {"next_url": f"{BASE}/issues/999/occurrences/?limit={PAGE_SIZE}&offset=100"},
            }
        )
        rows, _params = _run("occurrences", responses, _make_manager(state))
        assert rows == [{"id": 1, "issue_id": 10}]

    def test_checkpoints_completed_issue(self) -> None:
        # Finishing an issue must checkpoint it as completed so a crash before the next issue resumes
        # without re-pulling it.
        responses = {
            f"{BASE}/issues/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 10}, {"id": 20}], "next": None})],
            f"{BASE}/issues/10/occurrences/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 1}], "next": None})],
            f"{BASE}/issues/20/occurrences/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 3}], "next": None})],
        }
        manager = _make_manager()
        _run("occurrences", responses, manager)
        completed_sets = [
            call.args[0].fanout_state["completed"]
            for call in manager.save_state.call_args_list
            if call.args[0].fanout_state is not None
        ]
        assert ["/issues/10/occurrences/"] in completed_sets


class TestRetryClassification:
    @parameterized.expand([(429,), (500,), (503,)])
    @mock.patch(SLEEP_PATCH)
    def test_transient_status_is_retried_then_succeeds(self, status: int, _sleep: Any) -> None:
        # 429/5xx are transient — the client backs off and reissues the same request rather than
        # failing the whole sync.
        responses = {
            f"{BASE}/targets/?limit={PAGE_SIZE}": [
                _resp({"error": "transient"}, status=status),
                _resp({"results": [{"id": 1}], "next": None}),
            ],
        }
        rows, _params = _run("targets", responses, _make_manager())
        assert rows == [{"id": 1}]

    @parameterized.expand([(401,), (403,), (404,)])
    @mock.patch(SLEEP_PATCH)
    def test_client_error_fails_loud(self, status: int, _sleep: Any) -> None:
        # 4xx (other than 429) are permanent — raise rather than retry or silently sync 0 rows. A 401/
        # 403 is surfaced as a non-retryable credential error upstream via get_non_retryable_errors.
        responses = {
            f"{BASE}/targets/?limit={PAGE_SIZE}": [_resp({"error": "nope"}, status=status)],
        }
        with pytest.raises(requests.HTTPError):
            _run("targets", responses, _make_manager())


class TestUrlSafety:
    @parameterized.expand(
        [
            ("attacker_host", "https://evil.com/v1/targets/"),
            ("attacker_subdomain", "https://api.intruder.io.evil.com/v1/targets/"),
            ("userinfo_trick", "https://api.intruder.io@evil.com/v1/targets/"),
        ]
    )
    @mock.patch(SLEEP_PATCH)
    def test_off_host_next_url_is_refused(self, _name: str, evil_next: str, _sleep: Any) -> None:
        # A poisoned resume cursor or a malicious API-returned `next` pointing off the Intruder host
        # must never be followed with the bearer token — allowed_hosts=[] is the SSRF guard. The
        # first page is yielded, then following the off-host `next` raises before the request leaves
        # the process.
        responses = {
            f"{BASE}/targets/?limit={PAGE_SIZE}": [_resp({"results": [{"id": 1}], "next": evil_next})],
        }
        with pytest.raises(ValueError):
            _run("targets", responses, _make_manager())

    @mock.patch(SLEEP_PATCH)
    def test_redirect_is_refused(self, _sleep: Any) -> None:
        # A 3xx could retarget the authenticated request off-origin; allow_redirects=False refuses it
        # rather than following it with the token attached.
        responses = {f"{BASE}/targets/?limit={PAGE_SIZE}": [_redirect("https://evil.com")]}
        with pytest.raises(ValueError):
            _run("targets", responses, _make_manager())


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(INTRUDER_SESSION_PATCH)
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("tok") is expected

    @mock.patch(INTRUDER_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("tok") is False

    def test_redacts_token(self) -> None:
        # Dropping redact_values would leak the bearer token into logged URLs / captured samples.
        captured: dict[str, Any] = {}

        def fake_session(*_args: Any, **kwargs: Any) -> mock.MagicMock:
            captured.update(kwargs)
            session = mock.MagicMock()
            session.get.return_value = mock.MagicMock(status_code=200)
            return session

        with mock.patch(INTRUDER_SESSION_PATCH, side_effect=fake_session):
            validate_credentials("secret-token")
        assert captured.get("redact_values") == ("secret-token",)
