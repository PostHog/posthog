from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b import (
    E2BConfigurationError,
    E2BResumeConfig,
    E2BRetryableError,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source import E2BSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.e2b import E2BSourceConfig


def _driver(api_key: str = "e2b_test", team_id: str | None = None) -> SourceDriver:
    return SourceDriver(E2BSource(), E2BSourceConfig(api_key=api_key, team_id=team_id))


def _response(body: Any, *, next_token: str | None = None, status: int = 200) -> ScriptedResponse:
    headers = {"X-Next-Token": next_token} if next_token is not None else {}
    return ScriptedResponse(status=status, json=body, headers=headers)


class TestPagination:
    def test_non_list_response_fails_loudly(self) -> None:
        # E2B list endpoints return a bare JSON array; a wrapped/error object on a 200 is a response-shape
        # change. data_selector_required makes it fail loud rather than syncing the object as a row.
        result = _driver().run("sandboxes", [_response({"code": 500, "message": "boom"})])
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)

    def test_builds_a_redacted_redirect_pinned_uncaptured_session(self) -> None:
        # The sync session carries the X-API-Key header the scrubber can't see, so it must redact the
        # key and refuse redirects; capture=False keeps secret-bearing sandbox metadata out of sample
        # storage, which the row-level scrub can't do (it only runs after capture).
        result = _driver(api_key="e2b_secret").run("sandboxes", [_response([])])
        assert result.raised is None
        assert result.session_options == [
            {"redact_values": ("e2b_secret",), "allow_redirects": False, "capture": False}
        ]

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_retry_then_succeed(self, _name: str, status: int) -> None:
        # A rate limit or 5xx is transient — the framework transport must retry rather than fail the sync.
        result = _driver().run("sandboxes", [_response(None, status=status), _response([{"sandboxID": "a"}])])
        assert result.raised is None
        assert result.rows == [{"sandboxID": "a"}]
        assert result.paths == ["/v2/sandboxes", "/v2/sandboxes"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_code_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([_response(None, status=status)]) as network:
            ok, error = validate_credentials("e2b_test")
        assert ok is expected
        assert (error is None) is expected
        assert network.requests_log[0].path == "/v2/sandboxes"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["x-api-key"] == "e2b_test"
        # The key rides in the X-API-Key header, which the generic scrubber's denylist doesn't cover, so
        # the probe must redact it, pin redirects off to stop it replaying elsewhere, and disable capture
        # so the sandbox response body never reaches sample storage.
        assert network.session_options == [{"redact_values": ("e2b_test",), "allow_redirects": False, "capture": False}]

    # A key scoped to another team has to be re-scoped, not replaced, so a 403 must not read as a
    # revoked key and send someone off to generate another one that fails the same way.
    @parameterized.expand([(401, "invalid or has been revoked"), (403, "does not have access to this data")])
    def test_a_revoked_key_and_a_key_without_access_read_differently(self, status: int, expected: str) -> None:
        with scripted_network([_response(None, status=status)]):
            ok, error = validate_credentials("e2b_test")
        assert ok is False
        assert expected in (error or "")

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_transient_status_raises_rather_than_reporting_invalid(self, _name: str, status: int) -> None:
        # A rate limit or 5xx says nothing about the key; mapping it to "invalid" sends the user the wrong way.
        with scripted_network([_response(None, status=status)]):
            with pytest.raises(E2BRetryableError):
                validate_credentials("e2b_test")

    def test_network_error_is_treated_as_transient(self) -> None:
        # A connection failure is transient — it must surface as a retryable error, not a False "invalid key".
        with scripted_network([ConnectionResetError("connection reset")]):
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
        result = _driver(team_id="prj_1").run(endpoint, [_response([])])
        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == expected_pks
        assert result.response.sort_mode == "asc"
        if expected_partition is None:
            assert result.response.partition_keys is None
            assert result.response.partition_mode is None
        else:
            assert result.response.partition_keys == [expected_partition]
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_format == "week"


class TestFanout:
    def test_fanout_checkpoints_under_its_own_slot_and_resumes_from_it(self) -> None:
        # Fan-out resume state is a completed-parents map, not a page cursor, so it must not be
        # written into next_token — replaying that against the API would be meaningless.
        result = _driver().run(
            "template_builds",
            [
                _response([{"templateID": "t1"}, {"templateID": "t2"}]),
                _response({"builds": [{"buildID": "b1"}]}),
                _response({"builds": [{"buildID": "b2"}]}),
            ],
        )
        assert result.raised is None
        saved = result.saved_states[-1]
        assert saved.next_token is None
        assert saved.fanout is not None and sorted(saved.fanout["completed"]) == ["/templates/t1", "/templates/t2"]


class TestLatestSandboxMetrics:
    def test_walks_the_whole_sandbox_list_starting_from_a_resumed_cursor(self) -> None:
        # The iterator drives the sandbox list itself, so it has to seed a resumed run from the saved
        # cursor and keep chasing the header token; stopping after one page leaves most sandboxes
        # with no metrics at all.
        result = _driver().run(
            "sandbox_metrics_latest",
            [
                _response([{"sandboxID": "s9"}], next_token="t2"),
                _response({"sandboxes": {"s9": {"cpuUsedPct": 9.0}}}),
                _response([{"sandboxID": "s10"}]),
                _response({"sandboxes": {"s10": {"cpuUsedPct": 10.0}}}),
            ],
            resume_state=E2BResumeConfig(next_token="tok"),
        )
        assert result.raised is None
        assert result.rows == [{"cpuUsedPct": 9.0, "sandboxID": "s9"}, {"cpuUsedPct": 10.0, "sandboxID": "s10"}]
        assert result.paths == ["/v2/sandboxes", "/sandboxes/metrics", "/v2/sandboxes", "/sandboxes/metrics"]
        assert result.params("nextToken") == ["tok", None, "t2", None]

    def test_missing_sandboxes_key_fails_loudly(self) -> None:
        result = _driver().run(
            "sandbox_metrics_latest", [_response([{"sandboxID": "s1"}]), _response({"error": "nope"})]
        )
        assert isinstance(result.raised, ValueError)
        assert "data_selector" in str(result.raised)


class TestTeamMetrics:
    @parameterized.expand([("missing", None), ("blank", "   "), ("path_traversal", "../admin/teams")])
    def test_an_unusable_team_id_fails_before_any_request(self, _name: str, team_id: str | None) -> None:
        # The value lands in a request path, so anything but an opaque identifier must be refused
        # rather than interpolated.
        result = _driver(team_id=team_id).run("team_metrics", [])
        assert isinstance(result.raised, E2BConfigurationError)
        assert result.requests == []
