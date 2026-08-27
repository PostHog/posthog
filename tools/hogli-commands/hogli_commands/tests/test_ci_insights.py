from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli_commands import ci_insights, posthog_auth

_TOKEN = "phx_test_key_do_not_leak"

_SOURCES = [
    {"id": "src-other", "repo": "PostHog/posthog.com", "prefix": "website", "synced": True},
    {"id": "src-unsynced", "repo": "PostHog/posthog", "prefix": "", "synced": False},
    {"id": "src-good", "repo": "PostHog/posthog", "prefix": "eng_analytics", "synced": True},
]

_MASTER = {
    "default_branch": "master",
    "settled_workflows": 61,
    "failing_workflows": 2,
    "failing_workflow_names": ["ci-backend", "ci-frontend"],
}


def _row(test_id: str, *, state: str = "flaky", signature: str = "AssertionError", **overrides: Any) -> dict[str, Any]:
    return {
        "fingerprint": f"{test_id} | {signature}",
        "test_id": test_id,
        "error_signature": signature,
        "job_name": "Django tests (1/19)",
        "repo": "PostHog/posthog",
        "state": state,
        "first_seen": "2026-08-04T10:00:00Z",
        "last_seen": "2026-08-04T13:00:00Z",
        "occurrences": 4,
        "branches": 2,
        "master_hits": 0,
        "latest_run_id": 30912586404,
        "latest_branch": "feat/thing",
        "trend_24h": [0] * 22 + [4, 0],
        **overrides,
    }


_ROWS = [
    _row("posthog/api/test/test_capture.py::test_event", state="breaking_master", master_hits=9),
    # A third of this repo's PR rows are merge-queue gate attempts, so this state is common here.
    _row("posthog/test/test_migrations.py::test_forward", state="blocking_merge_queue"),
    _row("posthog/hogql/test/test_resolver.py::test_join", state="novel_burst"),
    _row("products/logs/test_query.py::test_severity", state="pr_only"),
]

_BROKEN = {
    "rows": _ROWS,
    "breaking_master_jobs": ["ci-backend / Django tests"],
    "window_days": 2,
    "truncated": False,
    "limit": 200,
}

_MASTER_FAILURES = [
    {
        "repo": {"provider": "github", "owner": "PostHog", "name": "posthog"},
        "workflow_name": "ci-frontend",
        "failed_job": "Jest tests",
        "run_count": 18,
        "first_seen": "2026-08-04T09:00:00Z",
        "last_seen": "2026-08-04T13:00:00Z",
        "latest_run_id": 30912401882,
    }
]

_FLAKY = {
    "items": [
        {
            "runner": "pytest",
            "nodeid": "posthog/api/test/test_capture.py::test_event",
            "selector": "posthog/api/test/test_capture.py::TestCapture::test_event",
            "classification": "confirmed_flake",
            "same_commit_recovery_run_count": 2,
            "failed_run_count": 12,
            "failed_pr_count": 5,
            "master_failed_run_count": 1,
            "quarantined_failed_run_count": 0,
            "last_signal_at": "2026-08-04T13:00:00Z",
        }
    ],
    "truncated": False,
    "limit": 200,
}

_PAYLOADS: dict[str, Any] = {
    "sources": _SOURCES,
    "current_branch_health": _MASTER,
    "broken_tests": _BROKEN,
    "master_failures": _MASTER_FAILURES,
    "flaky_tests": _FLAKY,
    "resolve_branch": [{"repo": "PostHog/posthog", "number": 77271, "title": "Do a thing", "state": "open"}],
    "run_failure_logs": {
        "run_id": 30912586404,
        "logs_available": True,
        "truncated": False,
        "jobs": [
            {
                "job_id": 1,
                "run_id": 30912586404,
                "conclusion": "failure",
                "branch": "feat/thing",
                "original_total_lines": 900,
                "line_count": 2,
                "truncated": False,
                "lines": [{"original_line": 42, "text": "FAILED x::y"}, {"original_line": None, "text": "... 3 lines"}],
            }
        ],
    },
}


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class _Recorder:
    def __init__(
        self,
        *,
        status: int = 200,
        payload: Any = None,
        fail: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._status = status
        self._payload = payload
        self._fail = fail
        self._overrides = overrides or {}

    def __call__(self, url: str, *, token: str, params: dict[str, Any], timeout: float) -> _Response:
        self.calls.append({"url": url, "token": token, "params": params, "timeout": timeout})
        action = url.rstrip("/").rsplit("/", 1)[-1]
        if self._status != 200 and action != "sources":
            return _Response(self._status, self._payload)
        if self._fail == action:
            return _Response(500, {"detail": "upstream exploded"})
        return _Response(200, self._overrides.get(action, _PAYLOADS[action]))

    def actions(self) -> set[str]:
        return {call["url"].rstrip("/").rsplit("/", 1)[-1] for call in self.calls}

    def params_for(self, action: str) -> dict[str, Any]:
        return next(call["params"] for call in self.calls if call["url"].rstrip("/").endswith(action))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def repo_checkout() -> Iterator[None]:
    # Stand in a PostHog/posthog checkout on a feature branch.
    with patch.object(
        ci_insights,
        "_git",
        side_effect=lambda *args: "git@github.com:PostHog/posthog.git" if args[0] == "remote" else "feat/thing",
    ):
        yield


# A signed-in caller. How a token is obtained is posthog_auth's contract, tested there; this suite
# is about what ci:insights does once it has one.
@pytest.fixture(autouse=True)
def token(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in posthog_auth.KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", _TOKEN)


def _invoke(runner: CliRunner, argv: list[str], recorder: _Recorder) -> Any:
    with patch.object(ci_insights, "_request", recorder):
        return runner.invoke(ci_insights.ci_insights, argv)


# `hogli ci:insights --help` is exercised for every manifest `click:` entry by
# tools/hogli/tests/test_cli.py, so it has to work with nothing configured, which is why credentials
# are resolved inside each command body rather than the group callback.
@pytest.mark.parametrize("argv", [["--help"], ["search", "--help"], ["view", "--help"]])
def test_help_works_without_a_configured_key(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    result = runner.invoke(ci_insights.ci_insights, argv)
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "personal API key" not in result.output


# The debugging-ci-failures skill branches to `gh` on exit 78, so the code is contract, including
# when the failure comes from the shared auth module rather than from this one.
def test_an_unauthenticated_caller_exits_not_configured_with_the_hint_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in posthog_auth.KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    with patch.object(posthog_auth, "load", return_value=None):
        result = CliRunner(mix_stderr=False).invoke(ci_insights.ci_insights, [])
    assert result.exit_code == posthog_auth.EXIT_NOT_CONFIGURED
    assert "posthog:login" in result.stderr
    # Diagnostics stay off stdout so `--format json` consumers never parse them.
    assert result.stdout == ""


# A page of "unavailable" sections exiting 0 would read as "CI is fine".
def test_digest_fails_when_no_section_came_back(runner: CliRunner) -> None:
    result = _invoke(runner, ["--format", "text"], _Recorder(status=503, payload={"detail": "down"}))
    assert result.exit_code == 1
    assert "unavailable" not in result.output


def test_request_shape_and_no_key_in_output(runner: CliRunner) -> None:
    recorder = _Recorder()
    result = _invoke(runner, ["--format", "text"], recorder)
    assert result.exit_code == 0
    broken = next(call for call in recorder.calls if call["url"].endswith("broken_tests/"))
    assert broken["url"] == "https://us.posthog.com/api/projects/2/engineering_analytics/broken_tests/"
    assert broken["token"] == _TOKEN
    assert broken["params"] == {"source_id": "src-good", "repo": "PostHog/posthog"}
    assert recorder.params_for("master_failures")["date_from"] == "-24h"
    # A leaked key would land in every agent transcript that ran this command.
    assert _TOKEN not in result.output


def test_environment_key_is_not_sent_to_a_non_posthog_host(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    monkeypatch.setenv("POSTHOG_CI_INSIGHTS_HOST", "https://attacker.example")
    result = _invoke(runner, ["--format", "text"], recorder)
    assert result.exit_code == posthog_auth.EXIT_NOT_CONFIGURED
    assert recorder.calls == []
    assert "Refusing to send POSTHOG_PERSONAL_API_KEY" in result.output
    assert "hogli posthog:login --host https://attacker.example" in result.output


def test_host_must_be_an_origin(runner: CliRunner) -> None:
    recorder = _Recorder()
    result = _invoke(runner, ["--host", "https://us.posthog.com/api", "--format", "text"], recorder)
    assert result.exit_code == 1
    assert recorder.calls == []
    assert "must be an HTTP(S) origin" in result.output


@pytest.mark.parametrize(
    "status, detail, expected_exit, expected_text",
    [
        (401, "Invalid token", 78, "rejected the credential"),
        (403, "API key missing required scope 'engineering_analytics:read'", 78, "engineering_analytics:read"),
        (403, "This action requires feature flag 'engineering-analytics'", 78, "flag-gated"),
        (400, "Connect a GitHub data warehouse source to use engineering analytics.", 1, "warehouse access"),
        (404, "Not found.", 1, "project id may be wrong"),
        (500, "boom", 1, "failed (500)"),
    ],
)
def test_http_failures_become_actionable_messages(
    runner: CliRunner, status: int, detail: str, expected_exit: int, expected_text: str
) -> None:
    recorder = _Recorder(status=status, payload={"detail": detail})
    result = _invoke(runner, [], recorder)
    assert result.exit_code == expected_exit
    assert expected_text in result.output
    assert "Traceback" not in result.output


def test_api_payload_schema_drift_is_reported_before_rendering(runner: CliRunner) -> None:
    broken = {**_BROKEN, "rows": [{**_ROWS[0], "occurrences": "four"}]}
    result = _invoke(
        runner,
        ["view", "test_capture", "--format", "text"],
        _Recorder(overrides={"broken_tests": broken}),
    )
    assert result.exit_code == 1
    assert "broken_tests returned an invalid payload" in result.output
    assert "response.rows[0].occurrences must be an integer" in result.output


# Reading an unsynced or unrelated source would report another repo's CI as yours.
@pytest.mark.parametrize(
    "repo, expected",
    [
        ("PostHog/posthog", "src-good"),
        ("posthog/POSTHOG", "src-good"),
        ("PostHog/posthog.com", "src-other"),
    ],
)
def test_source_binding_prefers_the_synced_entry(runner: CliRunner, repo: str, expected: str) -> None:
    recorder = _Recorder()
    result = _invoke(runner, ["--repo", repo, "--format", "text"], recorder)
    assert result.exit_code == 0
    assert recorder.params_for("broken_tests")["source_id"] == expected


def test_unknown_repo_names_what_the_caller_can_read(runner: CliRunner) -> None:
    result = _invoke(runner, ["--repo", "PostHog/nope"], _Recorder())
    assert result.exit_code == 1
    assert "PostHog/posthog" in result.output


def test_digest_reports_every_row_state_and_discloses_the_cap(runner: CliRunner) -> None:
    recorder = _Recorder()
    result = _invoke(runner, ["--format", "text", "--limit", "2"], recorder)
    assert result.exit_code == 0
    assert "master" in result.output and "2 of 61 workflows failing" in result.output
    assert "4 distinct failures over 2d" in result.output
    assert "Showing 2 of 4" in result.output
    assert "PR #77271" in result.output
    # Every state present in the rows is named, so a class of failure can't go unmentioned.
    for state in ("breaking_master", "blocking_merge_queue", "novel_burst", "pr_only"):
        assert state in result.output


# A read that succeeds with no workflow behind it says nothing about the default branch. Rendering
# it as OK claims every workflow passed, which is the "CI is fine" misreport this digest exists to
# avoid, and the skills tell agents to report master health from here.
def test_digest_does_not_call_the_default_branch_green_without_data(runner: CliRunner) -> None:
    empty = {
        "default_branch": "master",
        "settled_workflows": 0,
        "failing_workflows": 0,
        "failing_workflow_names": [],
    }
    recorder = _Recorder(overrides={"current_branch_health": empty})
    result = _invoke(runner, ["--format", "text"], recorder)
    assert result.exit_code == 0
    assert "NO DATA" in result.output
    assert "0 of 0 workflows failing" not in result.output


# A partial outage is when this read is worth most, so it must not be all-or-nothing.
def test_digest_degrades_one_section_without_losing_the_rest(runner: CliRunner) -> None:
    result = _invoke(runner, ["--format", "text"], _Recorder(fail="master_failures"))
    assert result.exit_code == 0
    assert "unavailable" in result.output
    assert "4 distinct failures" in result.output


# A zero-filled section is a complete, well-formed claim that nothing is broken. JSON is the default
# for every non-tty caller, and the skills tell agents to report from the digest.
def test_digest_json_reports_a_failed_section_as_null_not_as_zero(runner: CliRunner) -> None:
    result = _invoke(runner, ["--json"], _Recorder(fail="broken_tests"))
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["broken_tests"] is None
    assert "broken_tests" in payload["unavailable"]


# Keyed by the internal section name, `broken` and `branch` name nothing in the payload, so a
# consumer cannot join the failure to the section, and `branch` collides with the branch name.
@pytest.mark.parametrize(
    "failed, key",
    [
        ("broken_tests", "broken_tests"),
        ("resolve_branch", "branch_pull_requests"),
        ("master_failures", "master_failures"),
    ],
)
def test_digest_json_keys_unavailable_by_the_section_it_describes(runner: CliRunner, failed: str, key: str) -> None:
    result = _invoke(runner, ["--json"], _Recorder(fail=failed))
    payload = json.loads(result.output)
    assert list(payload["unavailable"]) == [key]
    assert key in payload


# `--limit` is accepted on every subcommand, so text and --json must agree on how many matches
# exist: capping text silently while --json returns everything hides matches from one of them.
def test_search_honors_limit_and_discloses_what_it_dropped(runner: CliRunner) -> None:
    rows = [_row(f"posthog/test_{index}.py::test_it") for index in range(25)]
    broken = {**_BROKEN, "rows": rows}
    text = _invoke(
        runner,
        ["search", "test_it", "--format", "text", "--limit", "3"],
        _Recorder(overrides={"broken_tests": broken}),
    )
    assert text.exit_code == 0
    assert text.output.count("posthog/test_") == 3
    assert "Showing 3 of 25" in text.output
    every = _invoke(
        runner, ["search", "test_it", "--json", "--limit", "0"], _Recorder(overrides={"broken_tests": broken})
    )
    assert len(json.loads(every.output)["broken_tests"]) == 25


# The backend caps the flaky window at 30 days and 400s past it, which would discard the healthy
# broken-tests half of the search too.
def test_search_rejects_a_window_the_backend_will_not_serve(runner: CliRunner) -> None:
    result = _invoke(runner, ["search", "x", "--days", "45"], _Recorder())
    assert result.exit_code == 2
    assert "30" in result.output


# Independent reads: raising the first error would throw away results that came back fine.
def test_search_keeps_one_section_when_the_other_fails(runner: CliRunner) -> None:
    result = _invoke(runner, ["search", "test_event", "--format", "text"], _Recorder(fail="flaky_tests"))
    assert result.exit_code == 0
    # The ref, not the test id: the id is truncated to the terminal width when rendered.
    assert ci_insights._ref(_ROWS[0]["fingerprint"]) in result.output
    assert "test health" in result.output
    assert "unavailable: flaky_tests failed" in result.output


def test_search_json_marks_a_failed_section_as_unavailable(runner: CliRunner) -> None:
    result = _invoke(runner, ["search", "test_event", "--json"], _Recorder(fail="flaky_tests"))
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["broken_tests"]
    assert payload["flaky_tests"] is None
    assert "flaky_tests" in payload["unavailable"]


def test_search_discloses_when_the_endpoint_could_have_omitted_matches(runner: CliRunner) -> None:
    broken = {**_BROKEN, "rows": [], "truncated": True}
    recorder = _Recorder(overrides={"broken_tests": broken})
    text_result = _invoke(runner, ["search", "not_returned", "--format", "text"], recorder)
    assert text_result.exit_code == 0
    assert "no match in returned rows" in text_result.output
    assert "Endpoint cap reached; more matches may exist" in text_result.output

    json_result = _invoke(runner, ["search", "not_returned", "--json"], _Recorder(overrides={"broken_tests": broken}))
    payload = json.loads(json_result.output)
    assert payload["truncated"] is True
    assert payload["truncated_sections"] == ["broken_tests"]


# The endpoint writes `latest_run_id or 0`, so 0 means no run id was recorded. Treating it as absent
# blames log retention, which has nothing to do with the real cause.
def test_view_logs_explains_a_missing_run_id_rather_than_blaming_retention(runner: CliRunner) -> None:
    broken = {**_BROKEN, "rows": [_row("posthog/test_norun.py::test_it", latest_run_id=0)]}
    recorder = _Recorder(overrides={"broken_tests": broken})
    result = _invoke(runner, ["view", "test_norun", "--logs", "--format", "text"], recorder)
    assert result.exit_code == 0
    assert "no run id recorded" in result.output
    assert "run_failure_logs" not in recorder.actions()


# Auto-JSON plus an endpoint passthrough would dump the full payload into transcripts.
def test_digest_json_carries_only_the_shown_rows_and_no_sparklines(runner: CliRunner) -> None:
    result = _invoke(runner, ["--json", "--limit", "1"], _Recorder())
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["broken_tests"]["total"] == 4
    assert len(payload["broken_tests"]["rows"]) == 1
    assert payload["broken_tests"]["state_counts"]["breaking_master"] == 1
    assert "trend_24h" not in payload["broken_tests"]["rows"][0]
    assert payload["broken_tests"]["rows"][0]["ref"] == ci_insights._ref(_ROWS[0]["fingerprint"])


# CliRunner's stdout is not a tty, so "auto" must resolve to JSON there.
@pytest.mark.parametrize(
    "argv, expect_json",
    [
        ([], True),
        (["--format", "text"], False),
        (["--json"], True),
        # These options are declared on the group AND on every subcommand, so a value given
        # on one side must not be lost to the other side's default, and `--json` must not
        # outrank an explicit `--format` across that boundary.
        (["--json", "search", "test_capture"], True),
        (["search", "test_capture", "--json"], True),
        (["--json", "search", "test_capture", "--format", "text"], False),
        (["--format", "text", "search", "test_capture", "--json"], True),
        (["--format", "text", "search", "test_capture"], False),
    ],
)
def test_format_resolution(runner: CliRunner, argv: list[str], expect_json: bool) -> None:
    result = _invoke(runner, argv, _Recorder())
    assert result.exit_code == 0
    assert result.output.lstrip().startswith("{") is expect_json


# Dropping a group-level --repo/--host would silently answer about a different repo.
@pytest.mark.parametrize("argv", [["--repo", "PostHog/posthog.com", "view", "test_capture"], ["view", "test_capture"]])
def test_subcommands_inherit_group_level_options(runner: CliRunner, argv: list[str]) -> None:
    recorder = _Recorder()
    result = _invoke(runner, [*argv, "--format", "text"], recorder)
    assert result.exit_code == 0
    expected = "src-other" if "--repo" in argv else "src-good"
    assert recorder.params_for("broken_tests")["source_id"] == expected


def test_ref_is_stable_and_short() -> None:
    ref = ci_insights._ref(_ROWS[0]["fingerprint"])
    assert ref == ci_insights._ref(_ROWS[0]["fingerprint"])
    assert len(ref) == 8
    assert ref != ci_insights._ref(_ROWS[1]["fingerprint"])


# A ref printed by the digest has to be usable by view, so the two must not drift.
@pytest.mark.parametrize("ref_of", ["full_ref", "prefix", "fingerprint", "test_id_substring"])
def test_view_resolves_every_accepted_ref_form(runner: CliRunner, ref_of: str) -> None:
    row = _ROWS[0]
    ref = {
        "full_ref": ci_insights._ref(row["fingerprint"]),
        "prefix": ci_insights._ref(row["fingerprint"])[:4],
        "fingerprint": row["fingerprint"],
        "test_id_substring": "test_capture",
    }[ref_of]
    result = _invoke(runner, ["view", ref, "--format", "text"], _Recorder())
    assert result.exit_code == 0
    assert row["test_id"] in result.output
    assert "breaking_master: failing on the default branch" in result.output


def test_view_lists_candidates_when_a_ref_is_ambiguous(runner: CliRunner) -> None:
    result = _invoke(runner, ["view", "test_", "--format", "text"], _Recorder())
    assert result.exit_code == 1
    assert "matches 4 failures" in result.output


def test_view_points_at_the_digest_for_an_unknown_ref(runner: CliRunner) -> None:
    result = _invoke(runner, ["view", "deadbeef", "--format", "text"], _Recorder())
    assert result.exit_code == 1
    assert "hogli ci:insights" in result.output


def test_view_logs_reads_the_rows_latest_run(runner: CliRunner) -> None:
    recorder = _Recorder()
    result = _invoke(runner, ["view", "test_capture", "--logs", "--format", "text"], recorder)
    assert result.exit_code == 0
    assert recorder.params_for("run_failure_logs")["run_id"] == _ROWS[0]["latest_run_id"]
    assert "FAILED x::y" in result.output


def test_view_logs_discloses_the_run_level_cap_without_mislabeling_the_job(runner: CliRunner) -> None:
    logs = {
        **_PAYLOADS["run_failure_logs"],
        "truncated": True,
        "jobs": [{**_PAYLOADS["run_failure_logs"]["jobs"][0], "truncated": True}],
    }
    result = _invoke(
        runner,
        ["view", "test_capture", "--logs", "--format", "text"],
        _Recorder(overrides={"run_failure_logs": logs}),
    )
    assert result.exit_code == 0
    assert "Run log cap reached; later lines or jobs may be missing." in result.output
    assert "(job log output truncated)" in result.output
    assert "per-job line cap" not in result.output


def test_view_logs_strips_terminal_control_characters(runner: CliRunner) -> None:
    logs = {
        **_PAYLOADS["run_failure_logs"],
        "jobs": [
            {
                **_PAYLOADS["run_failure_logs"]["jobs"][0],
                "lines": [{"original_line": 42, "text": "\x1b]52;c;payload\x07\nFAILED x::y"}],
            }
        ],
    }
    result = _invoke(
        runner,
        ["view", "test_capture", "--logs", "--format", "text"],
        _Recorder(overrides={"run_failure_logs": logs}),
    )
    assert result.exit_code == 0
    assert "\x1b" not in result.output
    assert "\x07" not in result.output
    assert "]52;c;payloadFAILED x::y" in result.output


# Merging failure lines with the test-health queue would invent a verdict neither made.
def test_search_keeps_the_two_grains_in_separate_sections(runner: CliRunner) -> None:
    recorder = _Recorder()
    result = _invoke(runner, ["search", "test_capture", "--format", "text"], recorder)
    assert result.exit_code == 0
    assert "broken tests" in result.output and "test health" in result.output
    assert "confirmed_flake" in result.output
    assert recorder.params_for("flaky_tests")["date_from"] == "-7d"


def test_search_with_no_match_states_what_it_cannot_see(runner: CliRunner) -> None:
    result = _invoke(runner, ["search", "nothing_matches_this", "--format", "text"], _Recorder())
    assert result.exit_code == 0
    assert result.output.count("no match") == 2
    assert "non-pytest" in result.output


def test_search_json_reports_both_surfaces(runner: CliRunner) -> None:
    result = _invoke(runner, ["search", "test_capture", "--json"], _Recorder())
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [row["test_id"] for row in payload["broken_tests"]] == [_ROWS[0]["test_id"]]
    assert len(payload["flaky_tests"]) == 1
