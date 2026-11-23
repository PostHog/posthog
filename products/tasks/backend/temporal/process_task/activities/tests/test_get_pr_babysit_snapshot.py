import uuid
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

import responses
from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.github.merge_queue import MergeQueueState
from posthog.models.github_integration_base import GitHubIntegrationBase

from products.tasks.backend.exceptions import GitHubRateLimitedError, ProcessTaskTransientError
from products.tasks.backend.temporal.babysit_pr.snapshot import BODY_EXCERPT_MAX_CHARS, FailingCheck, PRSnapshot
from products.tasks.backend.temporal.process_task.activities.get_pr_babysit_snapshot import (
    GetPrBabysitSnapshotInput,
    get_pr_babysit_snapshot,
)
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    DEFAULT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.tests.gitlab_fakes import (
    GITLAB_API,
    GITLAB_BOT,
    MR_URL,
    gitlab_merge_request,
    gitlab_task_context,
)

GET_PR_CONTEXT_MODULE = "products.tasks.backend.temporal.process_task.activities.get_pr_context"

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
        integration.parse_pull_request_url = GitHubIntegrationBase.parse_pull_request_url
        integration.get_pull_request_merge_queue_state.return_value = None
        return integration

    @pytest.mark.django_db
    def test_returns_none_when_snapshot_fetch_reports_failure(self, test_task_run):
        test_task_run.output = {"pr_url": PR_URL}
        test_task_run.save(update_fields=["output"])

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(
            f"{GET_PR_CONTEXT_MODULE}.get_github_integration",
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
        integration = self._integration_returning(raw)
        integration.get_pull_request_merge_queue_state.return_value = MergeQueueState.TESTING
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
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
        assert snapshot.merge_queue_push_would_eject is True

    @pytest.mark.django_db
    def test_merged_pr_skips_the_queue_read(self, test_task_run):
        test_task_run.output = {"pr_url": PR_URL}
        test_task_run.save(update_fields=["output"])

        integration = self._integration_returning({"success": True, "url": PR_URL, "state": "merged"})
        integration.get_pull_request_merge_queue_state.side_effect = RuntimeError("comments unavailable")
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
            snapshot = self._run(self._ctx(run_id=str(test_task_run.id)))

        assert snapshot is not None
        assert snapshot.is_terminal

    @pytest.mark.django_db
    def test_raises_transient_error_when_github_call_raises(self, test_task_run):
        test_task_run.output = {"pr_url": PR_URL}
        test_task_run.save(update_fields=["output"])

        integration = MagicMock()
        integration.get_pull_request_babysit_snapshot.side_effect = RuntimeError("GitHub exploded")

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
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
            patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration),
            patch("products.tasks.backend.exceptions.capture_exception") as mock_capture,
        ):
            with pytest.raises(GitHubRateLimitedError) as exc_info:
                self._run(ctx)

        assert exc_info.value.non_retryable is False
        assert exc_info.value.next_retry_delay == timedelta(seconds=expected_backoff)
        mock_capture.assert_not_called()


@pytest.fixture
def gitlab_context(test_task_run):
    with patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None)):
        yield gitlab_task_context(test_task_run)


class TestGetGitLabBabysitSnapshotActivity:
    @pytest.mark.django_db
    def test_maps_pipeline_discussions_and_comments_and_stores_the_merge_request_state(
        self, test_task_run, gitlab_context
    ):
        test_task_run.output = {"pr_url": MR_URL}
        test_task_run.save(update_fields=["output"])
        reviewer = {"id": 5, "username": "reviewer"}
        outsider = {"id": 6, "username": "outsider"}
        discussions = [
            {
                "id": "d-open",
                "individual_note": False,
                "notes": [
                    {
                        "id": 101,
                        "body": "Rename this",
                        "author": outsider,
                        "system": False,
                        "resolvable": True,
                        "resolved": False,
                        "position": {"new_path": "app/widget.py"},
                    },
                    {
                        "id": 102,
                        "body": "Still unclear",
                        "author": reviewer,
                        "system": False,
                        "resolvable": True,
                        "resolved": False,
                    },
                ],
            },
            {
                "id": "d-resolved",
                "individual_note": False,
                "notes": [{"id": 103, "body": "ok", "author": reviewer, "resolvable": True, "resolved": True}],
            },
            {
                "id": "d-system",
                "individual_note": True,
                "notes": [{"id": 104, "body": "added 1 commit", "author": reviewer, "system": True}],
            },
            {
                "id": "d-bot",
                "individual_note": True,
                "notes": [{"id": 105, "body": "Opened by the agent", "author": GITLAB_BOT, "system": False}],
            },
            {
                "id": "d-comment",
                "individual_note": True,
                "notes": [{"id": 106, "body": "Why this approach?", "author": outsider, "system": False}],
            },
        ]
        trace = (
            "section_start:1700000000:step_script\r\x1b[0K\x1b[32;1mRunning tests\x1b[0;m\n"
            "progress 10%\rprogress 100%\n"
            "FAILED tests/test_widget.py::test_size\n"
        )
        with responses.RequestsMock() as gitlab:
            gitlab.get(f"{GITLAB_API}/merge_requests/3", json=gitlab_merge_request())
            gitlab.get(f"{GITLAB_API}/merge_requests/3/discussions", json=discussions)
            gitlab.get(f"{GITLAB_API}/members/all/5", json={"id": 5, "access_level": 30, "state": "active"})
            gitlab.get(f"{GITLAB_API}/members/all/6", status=404, json={"message": "404 Not found"})
            gitlab.get(
                f"{GITLAB_API}/pipelines/55/jobs",
                json=[
                    {"id": 900, "name": "test", "web_url": f"{MR_URL}/jobs/900", "allow_failure": False},
                    {"id": 901, "name": "lint", "web_url": f"{MR_URL}/jobs/901", "allow_failure": True},
                ],
            )
            gitlab.get(f"{GITLAB_API}/jobs/900/trace", body=trace)

            snapshot = get_pr_babysit_snapshot(GetPrBabysitSnapshotInput(context=gitlab_context))

        assert snapshot is not None
        assert (snapshot.pr_url, snapshot.pr_state, snapshot.head_sha, snapshot.head_ref) == (
            MR_URL,
            "draft",
            "abc123",
            "posthog/fix-widget",
        )
        assert (snapshot.ci_status, snapshot.has_conflict, snapshot.mergeable, snapshot.review_threads_complete) == (
            "failing",
            False,
            True,
            True,
        )
        assert snapshot.failing_checks == [
            FailingCheck(
                key="test",
                details_url=f"{MR_URL}/jobs/900",
                log_excerpt="Running tests\nprogress 100%\nFAILED tests/test_widget.py::test_size",
            )
        ]
        assert [
            (thread.id, thread.last_comment_id, thread.path, thread.author, thread.author_association, thread.url)
            for thread in snapshot.unresolved_threads
        ] == [("d-open", "102", "app/widget.py", "reviewer", "DEVELOPER", f"{MR_URL}#note_102")]
        assert [(comment.id, comment.author, comment.author_association) for comment in snapshot.comments] == [
            ("106", "outsider", None)
        ]
        test_task_run.refresh_from_db()
        assert (test_task_run.output["pr_state"], test_task_run.output["ci_status"]) == ("draft", "failing")

    @pytest.mark.parametrize(
        "gitlab_state, expected_state, expected_merged",
        [("merged", "merged", True), ("closed", "closed", None), ("locked", "closed", None)],
    )
    @pytest.mark.django_db
    def test_terminal_merge_request_stores_its_state_and_keeps_the_last_ci_status(
        self, test_task_run, gitlab_context, gitlab_state, expected_state, expected_merged
    ):
        test_task_run.output = {"pr_url": MR_URL, "pr_state": "open", "ci_status": "passing"}
        test_task_run.save(update_fields=["output"])

        with responses.RequestsMock() as gitlab:
            gitlab.get(f"{GITLAB_API}/merge_requests/3", json=gitlab_merge_request(state=gitlab_state, draft=False))
            snapshot = get_pr_babysit_snapshot(GetPrBabysitSnapshotInput(context=gitlab_context))

        assert snapshot is not None
        assert snapshot.is_terminal
        test_task_run.refresh_from_db()
        assert test_task_run.output["pr_state"] == expected_state
        assert test_task_run.output.get("pr_merged") is expected_merged
        assert test_task_run.output["ci_status"] == "passing"

    @pytest.mark.django_db
    def test_merge_request_outside_the_connected_project_is_never_read(self, test_task_run, gitlab_context):
        test_task_run.output = {"pr_url": "https://gitlab.com/acme/other/-/merge_requests/3"}
        test_task_run.save(update_fields=["output"])

        with responses.RequestsMock():
            assert get_pr_babysit_snapshot(GetPrBabysitSnapshotInput(context=gitlab_context)) is None
