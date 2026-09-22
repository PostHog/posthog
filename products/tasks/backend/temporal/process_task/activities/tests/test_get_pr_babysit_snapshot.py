import uuid
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError

from products.tasks.backend.exceptions import GitHubRateLimitedError, ProcessTaskTransientError
from products.tasks.backend.temporal.babysit_pr.snapshot import BODY_EXCERPT_MAX_CHARS, PRSnapshot
from products.tasks.backend.temporal.process_task.activities.get_pr_babysit_snapshot import (
    GetPrBabysitSnapshotInput,
    get_pr_babysit_snapshot,
)
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    DEFAULT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

GET_PR_BABYSIT_SNAPSHOT_MODULE = "products.tasks.backend.temporal.process_task.activities.get_pr_babysit_snapshot"

PR_URL = "https://github.com/acme/widgets/pull/7"


class TestSnapshotFromRaw:
    def test_long_bodies_are_truncated_with_a_marker(self):
        raw = {
            "unresolved_threads": [{"id": "T1", "body": "x" * (BODY_EXCERPT_MAX_CHARS + 500)}],
            "comments": [{"id": "M1", "body": "y" * (BODY_EXCERPT_MAX_CHARS + 500)}],
        }

        snapshot = PRSnapshot.from_raw(raw, PR_URL)

        for excerpt, filler in (
            (snapshot.unresolved_threads[0].body_excerpt, "x"),
            (snapshot.comments[0].body_excerpt, "y"),
        ):
            assert excerpt.startswith(filler * BODY_EXCERPT_MAX_CHARS)
            assert "truncated" in excerpt[BODY_EXCERPT_MAX_CHARS:]

    def test_body_at_the_limit_is_kept_whole(self):
        raw = {"comments": [{"id": "M1", "body": "y" * BODY_EXCERPT_MAX_CHARS}]}

        snapshot = PRSnapshot.from_raw(raw, PR_URL)

        assert snapshot.comments[0].body_excerpt == "y" * BODY_EXCERPT_MAX_CHARS

    @parameterized.expand(
        [
            ("unresolved_threads",),
            ("comments",),
        ]
    )
    def test_items_without_an_id_are_dropped(self, key):
        raw = {key: [{"id": None, "body": "no id"}, {"id": "ok", "body": "kept"}]}

        snapshot = PRSnapshot.from_raw(raw, PR_URL)

        assert [item.id for item in getattr(snapshot, key)] == ["ok"]

    def test_missing_keys_fall_back_to_non_actionable_defaults(self):
        snapshot = PRSnapshot.from_raw({}, PR_URL)

        assert snapshot.pr_url == PR_URL
        assert snapshot.pr_state == "unknown"
        assert snapshot.has_conflict is False
        assert snapshot.is_terminal is False
        assert snapshot.failing_checks == []


@pytest.mark.requires_secrets
class TestGetPrBabysitSnapshotActivity:
    def _ctx(self, *, run_id: str) -> TaskProcessingContext:
        return TaskProcessingContext(
            task_id="task-1",
            run_id=run_id,
            team_id=1,
            team_uuid=str(uuid.uuid4()),
            organization_id=str(uuid.uuid4()),
            github_integration_id=1,
            repository="acme/widgets",
            distinct_id="user-1",
            pr_loop_enabled=True,
            pr_babysit_enabled=True,
        )

    def _run(self, ctx: TaskProcessingContext):
        return get_pr_babysit_snapshot(GetPrBabysitSnapshotInput(context=ctx))

    def _integration_returning(self, raw: dict) -> MagicMock:
        integration = MagicMock()
        integration.get_pull_request_babysit_snapshot.return_value = raw
        return integration

    @pytest.mark.django_db
    def test_returns_none_when_snapshot_fetch_reports_failure(self, test_task_run):
        test_task_run.output = {"pr_url": PR_URL}
        test_task_run.save(update_fields=["output"])

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(
            f"{GET_PR_BABYSIT_SNAPSHOT_MODULE}.get_github_integration",
            return_value=self._integration_returning({"success": False, "error": "not found"}),
        ):
            assert self._run(ctx) is None

    @pytest.mark.django_db
    def test_maps_the_raw_snapshot_into_the_decision_dataclass(self, test_task_run):
        test_task_run.output = {"pr_url": PR_URL}
        test_task_run.save(update_fields=["output"])

        raw = {
            "success": True,
            "url": PR_URL,
            "state": "open",
            "head_sha": "head1",
            "has_conflict": True,
            "author_login": "posthog-bot",
            "failing_checks": [{"key": "CI/backend", "details_url": "https://ci/1"}],
            "unresolved_threads": [
                {
                    "id": "T1",
                    "last_comment_id": "C1",
                    "path": "posthog/api.py",
                    "author": "reviewer",
                    "author_association": "MEMBER",
                    "body": "rename this",
                    "url": "https://github.com/acme/widgets/pull/7#discussion_r1",
                }
            ],
            "comments": [{"id": "M1", "author": "coderabbit", "body": "3 nits"}],
        }

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(
            f"{GET_PR_BABYSIT_SNAPSHOT_MODULE}.get_github_integration", return_value=self._integration_returning(raw)
        ):
            snapshot = self._run(ctx)

        assert snapshot is not None
        assert snapshot.pr_url == PR_URL
        assert snapshot.head_sha == "head1"
        assert snapshot.has_conflict is True
        assert snapshot.author_login == "posthog-bot"
        assert [check.key for check in snapshot.failing_checks] == ["CI/backend"]
        assert snapshot.failing_checks[0].details_url == "https://ci/1"
        thread = snapshot.unresolved_threads[0]
        assert (thread.id, thread.last_comment_id, thread.path) == ("T1", "C1", "posthog/api.py")
        assert thread.body_excerpt == "rename this"
        comment = snapshot.comments[0]
        assert (comment.id, comment.body_excerpt) == ("M1", "3 nits")

    @pytest.mark.django_db
    def test_raises_transient_error_when_github_call_raises(self, test_task_run):
        test_task_run.output = {"pr_url": PR_URL}
        test_task_run.save(update_fields=["output"])

        integration = MagicMock()
        integration.get_pull_request_babysit_snapshot.side_effect = RuntimeError("GitHub exploded")

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(f"{GET_PR_BABYSIT_SNAPSHOT_MODULE}.get_github_integration", return_value=integration):
            with pytest.raises(ProcessTaskTransientError) as exc_info:
                self._run(ctx)

        assert exc_info.value.non_retryable is False

    @pytest.mark.parametrize(
        "raised, expected_backoff",
        [
            (GitHubRateLimitError("resets at None", retry_after=60), 60),
            (GitHubEgressBudgetExhausted("shed"), DEFAULT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS),
        ],
    )
    @pytest.mark.django_db
    def test_rate_limit_stays_retryable_uncaptured_and_honors_backoff(self, raised, expected_backoff, test_task_run):
        test_task_run.output = {"pr_url": PR_URL}
        test_task_run.save(update_fields=["output"])

        integration = MagicMock()
        integration.get_pull_request_babysit_snapshot.side_effect = raised

        ctx = self._ctx(run_id=str(test_task_run.id))
        with (
            patch(f"{GET_PR_BABYSIT_SNAPSHOT_MODULE}.get_github_integration", return_value=integration),
            patch("products.tasks.backend.exceptions.capture_exception") as mock_capture,
        ):
            with pytest.raises(GitHubRateLimitedError) as exc_info:
                self._run(ctx)

        assert exc_info.value.non_retryable is False
        assert exc_info.value.next_retry_delay == timedelta(seconds=expected_backoff)
        mock_capture.assert_not_called()
