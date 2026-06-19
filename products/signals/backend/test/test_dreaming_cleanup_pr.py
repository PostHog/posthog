import pytest
from unittest.mock import MagicMock

from products.signals.backend.temporal.dreaming.cleanup_pr import (
    DREAMING_CLEANUP_BRANCH,
    DREAMING_CLEANUP_LABEL,
    DREAMING_PR_BODY_MARKER,
    CleanupFileEdit,
    CleanupPRError,
    reconcile_cleanup_pr,
)


def _edit() -> CleanupFileEdit:
    return CleanupFileEdit(path=".posthog/todo.md", content="# todo\n", commit_message="chore: todo")


def _github_with_no_open_prs() -> MagicMock:
    github = MagicMock()
    github.list_pull_requests.return_value = {"success": True, "pull_requests": []}
    github.get_branch_info.return_value = {"success": True, "exists": False}
    github.create_branch.return_value = {"success": True}
    github.update_file.return_value = {"success": True}
    github.create_pull_request.return_value = {
        "success": True,
        "pr_number": 7,
        "pr_url": "https://github.com/o/r/pull/7",
        "state": "open",
    }
    github.add_labels_to_issue.return_value = {"success": True}
    return github


class TestSingletonCleanupPR:
    def test_creates_pr_when_none_exists(self):
        github = _github_with_no_open_prs()

        result = reconcile_cleanup_pr(github, "repo", title="t", body="b", edits=[_edit()])

        assert result.action == "created"
        assert result.pr_number == 7
        github.create_pull_request.assert_called_once()
        github.add_labels_to_issue.assert_called_once_with("repo", 7, [DREAMING_CLEANUP_LABEL])
        # The branch was created and the file written before the PR opened.
        github.create_branch.assert_called_once_with("repo", DREAMING_CLEANUP_BRANCH)
        github.update_file.assert_called_once()

    def test_body_marker_is_injected(self):
        github = _github_with_no_open_prs()

        reconcile_cleanup_pr(github, "repo", title="t", body="just text", edits=[_edit()])

        _, kwargs = github.create_pull_request.call_args
        assert DREAMING_PR_BODY_MARKER in kwargs["body"]

    def test_updates_existing_labelled_pr_instead_of_creating(self):
        github = MagicMock()
        github.list_pull_requests.return_value = {
            "success": True,
            "pull_requests": [
                {
                    "number": 11,
                    "url": "https://github.com/o/r/pull/11",
                    "created_at": "2026-06-01T00:00:00Z",
                    "labels": [DREAMING_CLEANUP_LABEL],
                    "body": "",
                    "head_branch": DREAMING_CLEANUP_BRANCH,
                }
            ],
        }
        github.update_file.return_value = {"success": True}
        github.update_pull_request.return_value = {"success": True}

        result = reconcile_cleanup_pr(github, "repo", title="t", body="b", edits=[_edit()])

        assert result.action == "updated"
        assert result.pr_number == 11
        github.create_pull_request.assert_not_called()
        github.create_branch.assert_not_called()
        github.update_pull_request.assert_called_once()

    def test_recognizes_pr_by_body_marker_when_label_stripped(self):
        github = MagicMock()
        github.list_pull_requests.return_value = {
            "success": True,
            "pull_requests": [
                {
                    "number": 12,
                    "url": "u",
                    "created_at": "2026-06-01T00:00:00Z",
                    "labels": [],
                    "body": f"some text\n{DREAMING_PR_BODY_MARKER}",
                    "head_branch": DREAMING_CLEANUP_BRANCH,
                }
            ],
        }
        github.update_file.return_value = {"success": True}
        github.update_pull_request.return_value = {"success": True}

        result = reconcile_cleanup_pr(github, "repo", title="t", body="b", edits=[_edit()])

        assert result.action == "updated"
        github.create_pull_request.assert_not_called()

    def test_multiple_open_prs_updates_oldest_only_never_creates(self):
        github = MagicMock()
        github.list_pull_requests.return_value = {
            "success": True,
            "pull_requests": [
                {
                    "number": 20,
                    "url": "u20",
                    "created_at": "2026-06-05T00:00:00Z",
                    "labels": [DREAMING_CLEANUP_LABEL],
                    "body": "",
                    "head_branch": DREAMING_CLEANUP_BRANCH,
                },
                {
                    "number": 10,
                    "url": "u10",
                    "created_at": "2026-06-01T00:00:00Z",
                    "labels": [DREAMING_CLEANUP_LABEL],
                    "body": "",
                    "head_branch": DREAMING_CLEANUP_BRANCH,
                },
            ],
        }
        github.update_file.return_value = {"success": True}
        github.update_pull_request.return_value = {"success": True}

        result = reconcile_cleanup_pr(github, "repo", title="t", body="b", edits=[_edit()])

        # Oldest (created_at, then number) is canonical.
        assert result.action == "updated"
        assert result.pr_number == 10
        github.create_pull_request.assert_not_called()

    def test_no_edits_is_noop_and_touches_nothing(self):
        github = MagicMock()

        result = reconcile_cleanup_pr(github, "repo", title="t", body="b", edits=[])

        assert result.action == "noop"
        github.list_pull_requests.assert_not_called()
        github.create_pull_request.assert_not_called()

    def test_list_failure_raises(self):
        github = MagicMock()
        github.list_pull_requests.return_value = {"success": False, "error": "boom"}

        with pytest.raises(CleanupPRError):
            reconcile_cleanup_pr(github, "repo", title="t", body="b", edits=[_edit()])

    def test_create_pr_failure_raises(self):
        github = _github_with_no_open_prs()
        github.create_pull_request.return_value = {"success": False, "error": "nope"}

        with pytest.raises(CleanupPRError):
            reconcile_cleanup_pr(github, "repo", title="t", body="b", edits=[_edit()])

    def test_labeling_failure_does_not_duplicate_pr(self):
        github = _github_with_no_open_prs()
        github.add_labels_to_issue.side_effect = Exception("label api down")

        # Labeling is best-effort; a failure must not raise (which would re-run and risk a dup).
        result = reconcile_cleanup_pr(github, "repo", title="t", body="b", edits=[_edit()])
        assert result.action == "created"
