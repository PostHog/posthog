from __future__ import annotations

import json
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from products.posthog_ai.eval_harness.log_parser import ToolCall
from products.posthog_ai.eval_harness.scorers.contract import Scorer
from products.posthog_ai.eval_harness.test.acp_log_lines import (
    join_lines,
    prompt_line,
    tool_call_completed_line,
    tool_call_input_line,
    tool_call_start_line,
)
from products.signals.evals.inbox_consumer_fixture import FOR_USER_REPORTS, REPORTS, status_counts
from products.signals.evals.inbox_consumer_scorers import (
    AnswerStatesFact,
    AnswerSurfacesReports,
    AutomationProposed,
    PullRequestFramesReport,
    PullRequestLinksReport,
    ReportClaimed,
    ReportPulled,
    SeededReport,
    WithinBudget,
    claims_report,
    measure,
    pull_request_text,
    reads_inbox,
    returns_report,
    searches_inbox,
)
from products.signals.evals.inbox_consumer_seeders import seed_inbox
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

REPORT = SeededReport(id="0195c0de-0000-7000-8000-000000000001", title="Team invites crash")
OTHER_REPORT_ID = "0195c0de-0000-7000-8000-000000000002"


def _call(
    name: str, input: dict[str, Any] | None = None, *, output: str = "", is_error: bool = False, **times: str
) -> ToolCall:
    return ToolCall(
        name=name,
        input=input or {},
        output=output,
        is_error=is_error,
        call_id="call",
        position=0,
        raw_name=name,
        is_exec_unwrapped=False,
        sequence=0,
        **times,
    )


class TestInboxConsumerEvalScorers(SimpleTestCase):
    @parameterized.expand(
        [
            ("the list", _call("inbox-reports-list"), True),
            ("the personal ranking", _call("inbox-reports-for-me"), True),
            (
                "sql over the reports table",
                _call("execute-sql", {"query": "SELECT count() FROM system.inbox_reports"}),
                True,
            ),
            ("sql over another table", _call("execute-sql", {"query": "SELECT count() FROM events"}), False),
            ("a failed list call", _call("inbox-reports-list", is_error=True), False),
            ("a claim, which is a write", _call("inbox-reports-claim", {"id": REPORT.id}), False),
        ]
    )
    def test_reads_inbox(self, _name: str, call: ToolCall, expected: bool) -> None:
        assert reads_inbox(call) is expected

    @parameterized.expand(
        [
            ("the search tool", _call("inbox-reports-search", {"query": "invites"}), True),
            ("the list with a text filter", _call("inbox-reports-list", {"search": "invites"}), True),
            ("the list paged without a filter", _call("inbox-reports-list", {"limit": 100}), False),
            ("sql over the reports table", _call("execute-sql", {"query": "SELECT title FROM inbox_reports"}), True),
            ("a failed search", _call("inbox-reports-search", {"query": "invites"}, is_error=True), False),
        ]
    )
    def test_searches_inbox(self, _name: str, call: ToolCall, expected: bool) -> None:
        assert searches_inbox(call) is expected

    @parameterized.expand(
        [
            ("a retrieve of the report", _call("inbox-reports-retrieve", {"id": REPORT.id}), True),
            ("a retrieve under the id alias", _call("inbox-reports-retrieve", {"report_id": REPORT.id}), True),
            # Another report's body can mention this one, so only the requested id counts for a retrieve.
            (
                "a retrieve of another report",
                _call("inbox-reports-retrieve", {"id": OTHER_REPORT_ID}, output=REPORT.id),
                False,
            ),
            ("a list row with the id", _call("inbox-reports-list", output=f"id: {REPORT.id}"), True),
            ("a sql row with the title", _call("execute-sql", output=f"title: {REPORT.title}"), True),
            ("a list without the report", _call("inbox-reports-list", output=f"id: {OTHER_REPORT_ID}"), False),
        ]
    )
    def test_returns_report(self, _name: str, call: ToolCall, expected: bool) -> None:
        assert returns_report(call, REPORT) is expected

    @parameterized.expand(
        [
            ("a claim", _call("inbox-reports-claim", {"id": REPORT.id}), True),
            ("a release", _call("inbox-reports-claim", {"id": REPORT.id, "release": True}), False),
            ("a rejected claim", _call("inbox-reports-claim", {"id": REPORT.id}, is_error=True), False),
            ("a claim of another report", _call("inbox-reports-claim", {"id": OTHER_REPORT_ID}), False),
        ]
    )
    def test_claims_report(self, _name: str, call: ToolCall, expected: bool) -> None:
        assert claims_report(call, REPORT) is expected

    def test_pull_request_text_holds_the_command_and_its_body_file_only(self) -> None:
        calls = [
            _call("Write", {"file_path": "/tmp/body.md", "content": f"Report: /inbox/{REPORT.id}"}),
            _call("Write", {"file_path": "/repo/invite.ts", "content": "unrelated source"}),
            # The sandbox cannot push, so the command fails. The description it carried still counts.
            _call("Bash", {"command": "gh pr create --title 'Fix invites' --body-file /tmp/body.md"}, is_error=True),
        ]

        text = pull_request_text(calls)

        assert "gh pr create" in text
        assert REPORT.id in text
        assert "unrelated source" not in text
        assert pull_request_text(calls[:2]) == ""

    def test_measure_counts_calls_output_and_the_time_the_tools_span(self) -> None:
        calls = [
            _call(
                "inbox-reports-list", output="12345", started_at="2026-01-01T10:00:00Z", ended_at="2026-01-01T10:00:02Z"
            ),
            _call(
                "inbox-reports-retrieve",
                output="123",
                started_at="2026-01-01T10:00:05Z",
                ended_at="2026-01-01T10:00:09Z",
            ),
        ]

        assert measure(calls, "tool_calls") == 2
        assert measure(calls, "tool_output_chars") == 8
        assert measure(calls, "tool_seconds") == 9
        assert measure([_call("inbox-reports-list")], "tool_seconds") is None

    def test_status_counts_cover_every_seeded_report(self) -> None:
        assert sum(status_counts().values()) == len(REPORTS)


def _exec(tool: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return "mcp__posthog__exec", {"command": f"call {tool} {json.dumps(payload)}"}


def _agent_log(calls: list[tuple[tuple[str, dict[str, Any]], str, str]]) -> str:
    """An agent log in the format the harness stores: each entry is a tool call, its output and its status."""
    lines = [prompt_line("2026-01-01T10:00:00Z", "Implement the report.")]
    for index, ((name, raw_input), output, status) in enumerate(calls):
        call_id = f"call-{index}"
        lines += [
            tool_call_start_line(f"2026-01-01T10:00:{index * 2 + 1:02d}Z", call_id, name),
            tool_call_input_line(f"2026-01-01T10:00:{index * 2 + 1:02d}Z", call_id, raw_input),
            tool_call_completed_line(f"2026-01-01T10:00:{index * 2 + 2:02d}Z", call_id, output, status),
        ]
    return join_lines(lines)


PULL_REQUEST_URL = "https://github.com/example-org/example-repo/pull/7"
IMPLEMENTATION_RUN = {
    "prompt": "Implement the report.",
    "seed": {
        "reports": {
            "invite_without_email": {"id": REPORT.id, "title": REPORT.title},
            "pdf_preview": {"id": OTHER_REPORT_ID, "title": "PDF previews fail"},
        }
    },
    "raw_log": _agent_log(
        [
            (_exec("inbox-reports-retrieve", {"id": REPORT.id}), "title: Team invites crash", "completed"),
            (_exec("inbox-reports-claim", {"id": REPORT.id}), "claimed", "completed"),
            (
                ("Bash", {"command": f"gh pr create --title 'Fix invites' --body 'Report: /inbox/{REPORT.id}'"}),
                "error: no push access",
                "failed",
            ),
            (
                _exec("inbox-reports-claim", {"id": REPORT.id, "pull_requests": [PULL_REQUEST_URL]}),
                "claimed",
                "completed",
            ),
        ]
    ),
}


class TestInboxConsumerEvalScorersOnAgentLogs(SimpleTestCase):
    @parameterized.expand(
        [
            ("the report is pulled", ReportPulled(), {"report": "invite_without_email"}, 1.0),
            ("another report is not pulled", ReportPulled(), {"report": "pdf_preview"}, 0.0),
            ("the report is claimed", ReportClaimed(), {"report": "invite_without_email"}, 1.0),
            (
                "three inbox calls fit a budget of three, the git command is not one",
                WithinBudget("tool_calls"),
                {"max": 3},
                1.0,
            ),
            ("three inbox calls break a budget of two", WithinBudget("tool_calls"), {"max": 2}, 0.0),
            ("eight seconds of tools break a budget of five", WithinBudget("tool_seconds"), {"max": 5}, 0.0),
        ]
    )
    def test_scorer_reads_the_run(self, _name: str, scorer: Scorer, spec: dict[str, Any], expected: float) -> None:
        score = scorer._run_eval_sync(IMPLEMENTATION_RUN, {scorer._name(): spec})

        assert score.score == expected, score.metadata

    @parameterized.expand([(ReportPulled(),), (ReportClaimed(),), (WithinBudget("tool_calls"),)])
    def test_scorer_skips_a_case_that_does_not_ask_for_it(self, scorer: Scorer) -> None:
        assert scorer._run_eval_sync(IMPLEMENTATION_RUN, {"another_scorer": {}}).score is None

    @parameterized.expand([(PullRequestLinksReport(),), (PullRequestFramesReport(),)])
    def test_pull_request_judge_reads_the_command_and_the_drafted_description(self, judge: Any) -> None:
        draft = f"Title: Count uploads once they finish\n\nSelf-driving report with evidence: /inbox/{REPORT.id}"

        prepared = judge._prepare(
            IMPLEMENTATION_RUN | {"last_message": draft}, {judge._name(): {"report": "invite_without_email"}}
        )

        assert "gh pr create" in prepared["output"]["pull_request"]
        assert draft in prepared["output"]["pull_request"]
        assert prepared["expected"]["report_id"] == REPORT.id

    @parameterized.expand([(PullRequestLinksReport(),), (PullRequestFramesReport(),)])
    def test_pull_request_judge_fails_a_run_with_no_draft(self, judge: Any) -> None:
        prepared = judge._prepare(
            {"seed": IMPLEMENTATION_RUN["seed"]}, {judge._name(): {"report": "invite_without_email"}}
        )

        assert prepared.score == 0.0

    @parameterized.expand(
        [
            (AnswerStatesFact(), {"fact": "Five reports are ready."}),
            (AnswerSurfacesReports(), {"reports": [REPORT.title]}),
            (AutomationProposed(), {}),
        ]
    )
    def test_judge_reads_the_answer_written_before_a_button(self, judge: Any, spec: dict[str, Any]) -> None:
        answer = "Five reports are ready, and one waits for your input."
        output = {
            "prompt": "How many inbox reports are there?",
            "last_message": "The button above opens your inbox.",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "mcp__posthog__exec"},
                        {"type": "text", "text": answer},
                        {"type": "tool_use", "name": "mcp__posthog-code-tools__show_actions"},
                        {"type": "text", "text": "The button above opens your inbox."},
                    ],
                }
            ],
        }

        prepared = judge._prepare(output, {judge._name(): spec})

        assert answer in prepared["output"]["last_message"]


class TestInboxConsumerEvalSeeder(ClickhouseTestMixin, APIBaseTest):
    def test_seeded_reports_reach_the_inbox_the_agent_reads(self) -> None:
        seed = seed_inbox(CustomPromptSandboxContext(team_id=self.team.id, user_id=self.user.id))

        reports_url = f"/api/projects/{self.team.id}/signals/reports/"
        for_you = self.client.get(reports_url, {"view": "for_you", "count_only": "true"}).json()
        listed = self.client.get(reports_url, {"limit": 100}).json()

        assert set(seed["reports"]) == {report.key for report in REPORTS}
        assert for_you["count"] == len(FOR_USER_REPORTS)
        # The list hides suppressed reports by default, as the agent's first read of the inbox does.
        assert listed["count"] == len(REPORTS) - status_counts()["suppressed"]
        assert {issue["name"] for issue in seed["lookup_issues"]} >= {"Checkout API timeout", "Team invite rejected"}
