import json
from contextlib import contextmanager

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized

from products.docs_freshness.backend.tasks.tasks import check_pull_request_head
from products.tasks.backend.facade.sandbox import ExecutionResult

_MODULE = "products.docs_freshness.backend.logic.impact_check"
_HEAD_SHA = "a" * 40
_IMPACTED = [{"page": "support/widget.mdx", "kind": "ui-label", "claim": "Secret API Key", "guard": "renamed"}]
_PROMPT = (
    "PR {event.properties.pr_url} at {event.properties.head_sha}\n{event.properties.claims}\n{event.properties.pages}"
)


def _sandbox_result(command: str, exit_code: int, impacted: list[dict]) -> ExecutionResult:
    if command.startswith("cat "):
        return ExecutionResult(stdout=_PROMPT, stderr="", exit_code=0)
    return ExecutionResult(stdout=json.dumps(impacted), stderr="", exit_code=exit_code)


class TestCheckPullRequestHead(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @parameterized.expand(
        [
            ("flagged", _HEAD_SHA, 1, _IMPACTED, 1, ["flagged"], 1),
            ("flagged_redelivered", _HEAD_SHA, 1, _IMPACTED, 2, ["flagged", "flagged"], 1),
            ("clear", _HEAD_SHA, 0, [], 1, ["clear"], 0),
            ("superseded", "b" * 40, 0, [], 1, [], 0),
            ("unmergeable_after_final_retry", _HEAD_SHA, 4, [], 1, ["unmergeable"], 0),
        ]
    )
    def test_verdict_for_head(
        self, _name, current_head_sha, exit_code, impacted, deliveries, expected_verdicts, expected_agent_starts
    ) -> None:
        github = MagicMock()
        github.get_pull_request.return_value = {"success": True, "state": "open", "head_sha": current_head_sha}
        sandbox = MagicMock()
        sandbox.execute.side_effect = lambda command, **_kwargs: _sandbox_result(command, exit_code, impacted)
        captured: list[dict] = []

        @contextmanager
        def scoped_capture():
            yield lambda **event: captured.append(event)

        with (
            override_settings(
                DOCS_FRESHNESS_TEAM_ID=self.team.id,
                DOCS_FRESHNESS_OWNER_USER_ID=self.user.id,
                DOCS_FRESHNESS_TOOL_REF="main",
            ),
            patch(f"{_MODULE}.GitHubIntegration.first_for_team_repository", return_value=github),
            patch(f"{_MODULE}.get_sandbox_class") as sandbox_class,
            patch(f"{_MODULE}.tasks_facade.create_and_run_task") as create_and_run_task,
            patch(f"{_MODULE}.ph_scoped_capture", scoped_capture),
        ):
            sandbox_class.return_value.create.return_value = sandbox
            for _ in range(deliveries):
                check_pull_request_head.apply(
                    kwargs={"repository": "PostHog/posthog", "pr_number": 42, "head_sha": _HEAD_SHA},
                    retries=check_pull_request_head.max_retries,
                )

        assert [event["properties"]["verdict"] for event in captured] == expected_verdicts
        assert sandbox_class.return_value.create.called == bool(expected_verdicts)
        assert create_and_run_task.call_count == expected_agent_starts
        if expected_agent_starts:
            assert create_and_run_task.call_args.kwargs["posthog_mcp_scopes"] == []
            description = create_and_run_task.call_args.kwargs["description"]
            assert "https://github.com/PostHog/posthog/pull/42" in description
            assert '"claim": "Secret API Key"' in description
            assert '["support/widget.mdx"]' in description
            assert "guard" not in description
