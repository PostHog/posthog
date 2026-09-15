from dataclasses import replace
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import GitHubIntegration

from products.tasks.backend.logic.stream.turn_completion import turn_completed_successfully
from products.tasks.backend.temporal.babysit_pr.snapshot import PRSnapshot
from products.tasks.backend.temporal.process_task.activities import mark_pr_ready as ready_module
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.mark_pr_ready import MarkPrReadyInput, mark_pr_ready


@pytest.mark.parametrize(
    "change,requested",
    [
        ("none", True),
        ("disabled", False),
        ("failed_run", False),
        ("keep_draft", False),
        ("different_pr", False),
        ("different_repository", False),
        ("different_branch", False),
        ("unset_branch", True),
        ("unset_branch_changed", False),
        ("new_commit", False),
        ("new_feedback", False),
        ("github_failure", False),
    ],
)
def test_activity_rechecks_run_and_pr_before_requesting_review(monkeypatch, change, requested):
    context = TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid="team-1",
        organization_id="org-1",
        github_integration_id=1,
        repository="example/widgets",
        distinct_id="user-1",
    )
    pr_url = "https://github.com/example/widgets/pull/7"
    raw = {
        "success": True,
        "url": pr_url,
        "state": "draft",
        "head_sha": "head1",
        "head_ref": "posthog/change",
        "ci_status": "passing",
        "mergeable": True,
        "feedback_complete": True,
    }
    snapshot = PRSnapshot.from_raw(raw, pr_url)
    run = SimpleNamespace(status="in_progress", branch=raw["head_ref"], output={"pr_url": raw["url"]}, state={})
    github = MagicMock()
    github.mark_pull_request_ready_for_review.return_value = {"success": True, "changed": True}
    if change == "failed_run":
        run.status = "failed"
    elif change == "keep_draft":
        run.state["keep_draft"] = True
    elif change == "different_pr":
        run.output["pr_url"] = "https://github.com/example/widgets/pull/8"
    elif change == "different_repository":
        context = replace(context, repository="example/other")
    elif change == "different_branch":
        raw["head_ref"] = "other"
    elif change in ("unset_branch", "unset_branch_changed"):
        run.branch = None
        if change == "unset_branch_changed":
            raw["head_ref"] = "other"
    elif change == "new_commit":
        raw["head_sha"] = "head2"
    elif change == "new_feedback":
        raw["comments"] = [{"id": "comment-1", "body": "Please change the name"}]
    elif change == "github_failure":
        github.get_pull_request_babysit_snapshot.side_effect = RuntimeError("unavailable")
    github.get_pull_request_babysit_snapshot.return_value = raw
    monkeypatch.setattr(ready_module.posthoganalytics, "feature_enabled", lambda *args, **kwargs: change != "disabled")
    monkeypatch.setattr(ready_module, "get_github_integration", lambda _: github)
    with patch.object(ready_module.TaskRun.objects, "filter") as find_run:
        find_run.return_value.first.return_value = run
        assert mark_pr_ready(MarkPrReadyInput(context=context, snapshot=snapshot)) is requested
    assert github.mark_pull_request_ready_for_review.called is requested
    if requested:
        github.mark_pull_request_ready_for_review.assert_called_once_with(
            "example/widgets", 7, skip_labels=frozenset({"keep-draft", "no-ci"}), expected_head_sha="head1"
        )


@pytest.mark.parametrize("reason", ["end_turn", "cancelled", "error", "refusal", None])
def test_only_successful_completion_enables_handover(reason):
    for event in (
        {"type": "notification", "notification": {"result": {"stopReason": reason}}},
        {
            "type": "notification",
            "notification": {"method": "_posthog/turn_complete", "params": {"stopReason": reason}},
        },
        {"type": "pi_event", "event": {"type": "turn_completed", "stopReason": reason}},
    ):
        assert turn_completed_successfully(event) is (reason == "end_turn")


@pytest.mark.parametrize(
    "state,expected_reason",
    [
        ({"headRefOid": "head2"}, "head_changed"),
        ({"labels": {"nodes": [{"name": "Keep-Draft"}]}}, "label"),
        ({"timelineItems": {"nodes": [{"__typename": "ConvertToDraftEvent"}]}}, "draft_state_decided"),
        ({"isDraft": False}, "not_draft"),
        ({"state": "CLOSED"}, "closed"),
    ],
)
def test_final_github_read_preserves_new_commits_and_manual_choices(state, expected_reason):
    github = object.__new__(GitHubIntegration)
    pr = {"id": "PR_1", "state": "OPEN", "isDraft": True, "headRefOid": "head1", **state}
    with patch.object(github, "_gh_graphql", return_value={"repository": {"pullRequest": pr}}) as graphql:
        result = github.mark_pull_request_ready_for_review(
            "example/widgets", 7, expected_head_sha="head1", skip_labels={"keep-draft"}
        )
    assert result == {"success": True, "changed": False, "reason": expected_reason}
    graphql.assert_called_once()
