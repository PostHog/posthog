import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

import responses

from posthog.models.integration import GitHubIntegration

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.babysit_pr.snapshot import PRSnapshot
from products.tasks.backend.temporal.process_task.activities import mark_pr_ready as ready_module
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.mark_pr_ready import MarkPrReadyInput, mark_pr_ready
from products.tasks.backend.temporal.process_task.activities.tests.gitlab_fakes import (
    GITLAB_API,
    GITLAB_BOT,
    MR_URL,
    gitlab_merge_request,
    gitlab_task_context,
)

from ee.hogai.sandbox import turn_completed_successfully


@pytest.mark.parametrize(
    "change,requested",
    [
        ("none", True),
        ("failed_run", False),
        ("keep_draft", False),
        ("queued_followup", False),
        ("followup_queued_mid_flight", False),
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
        "review_threads_complete": True,
    }
    snapshot = PRSnapshot.from_raw(raw, pr_url)
    run = SimpleNamespace(
        status="in_progress",
        branch=raw["head_ref"],
        output={"pr_url": raw["url"]},
        state={},
        has_pending_followup_messages=False,
    )
    late_run = SimpleNamespace(**vars(run))
    github = MagicMock()
    github.mark_pull_request_ready_for_review.return_value = {"success": True, "changed": True}
    if change == "failed_run":
        run.status = "failed"
    elif change == "keep_draft":
        run.state["keep_draft"] = True
    elif change == "queued_followup":
        run.has_pending_followup_messages = True
    elif change == "followup_queued_mid_flight":
        late_run.has_pending_followup_messages = True
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
    monkeypatch.setattr(ready_module, "get_github_integration", lambda *_: github)
    with patch.object(ready_module.TaskRun.objects, "filter") as find_run:
        find_run.return_value.first.side_effect = [run, late_run]
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


@pytest.mark.parametrize(
    "labels, notes, marked",
    [
        ([], [], True),
        (["Keep-Draft"], [], False),
        ([], [{"id": 1, "system": True, "body": "marked this merge request as **draft**"}], False),
    ],
    ids=["ready", "keep_draft_label", "person_redrafted"],
)
@pytest.mark.django_db
def test_gitlab_merge_request_is_marked_ready_by_dropping_the_draft_prefix(test_task_run, labels, notes, marked):
    test_task_run.status = TaskRun.Status.IN_PROGRESS
    test_task_run.branch = "posthog/fix-widget"
    test_task_run.output = {"pr_url": MR_URL, "pr_state": "draft"}
    test_task_run.save(update_fields=["status", "branch", "output"])
    passing = {"id": 55, "sha": "abc123", "status": "success", "web_url": f"{MR_URL}/pipelines/55"}
    snapshot = PRSnapshot.from_raw(
        {
            "success": True,
            "url": MR_URL,
            "state": "draft",
            "head_sha": "abc123",
            "head_ref": "posthog/fix-widget",
            "author_login": GITLAB_BOT["username"],
            "ci_status": "passing",
            "mergeable": True,
            "review_threads_complete": True,
        },
        MR_URL,
    )

    with (
        patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None)),
        responses.RequestsMock(assert_all_requests_are_fired=False) as gitlab,
    ):
        context = gitlab_task_context(test_task_run)
        gitlab.get(f"{GITLAB_API}/merge_requests/3", json=gitlab_merge_request(head_pipeline=passing, labels=labels))
        gitlab.get(f"{GITLAB_API}/merge_requests/3/discussions", json=[])
        gitlab.get(f"{GITLAB_API}/merge_requests/3/notes", json=notes)
        gitlab.put(f"{GITLAB_API}/merge_requests/3", json=gitlab_merge_request(draft=False))

        assert mark_pr_ready(MarkPrReadyInput(context=context, snapshot=snapshot)) is marked
        updates = [json.loads(call.request.body) for call in gitlab.calls if call.request.method == "PUT"]

    assert updates == ([{"title": "Fix the widget"}] if marked else [])
    test_task_run.refresh_from_db()
    assert test_task_run.output["pr_state"] == ("open" if marked else "draft")
