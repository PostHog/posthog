import uuid

import pytest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ObjectDoesNotExist

from products.tasks.backend.temporal.exceptions import TaskInvalidStateError
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    GetPrContextInput,
    GetPrContextOutput,
    compute_pr_fingerprint,
    get_github_integration,
    get_pr_context,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

GET_PR_CONTEXT_MODULE = "products.tasks.backend.temporal.process_task.activities.get_pr_context"


class TestComputePrFingerprint:
    def test_is_deterministic_for_same_input(self):
        pr = {"url": "https://api.github.com/repos/org/repo/pulls/1", "updated_at": "2026-04-23T10:00:00Z"}
        assert compute_pr_fingerprint(pr) == compute_pr_fingerprint(pr)

    def test_changes_when_updated_at_changes(self):
        base = {"url": "https://api.github.com/repos/org/repo/pulls/1"}
        earlier = compute_pr_fingerprint({**base, "updated_at": "2026-04-23T10:00:00Z"})
        later = compute_pr_fingerprint({**base, "updated_at": "2026-04-23T10:05:00Z"})
        assert earlier != later

    def test_changes_when_url_changes(self):
        base = {"updated_at": "2026-04-23T10:00:00Z"}
        a = compute_pr_fingerprint({**base, "url": "https://api.github.com/repos/org/repo/pulls/1"})
        b = compute_pr_fingerprint({**base, "url": "https://api.github.com/repos/org/repo/pulls/2"})
        assert a != b

    def test_handles_missing_keys_without_raising(self):
        fp = compute_pr_fingerprint({})
        assert isinstance(fp, str)
        assert len(fp) == 64  # sha256 hex digest


@pytest.mark.requires_secrets
class TestGetPrContextActivity:
    def _ctx(self, *, run_id: str, github_integration_id: int | None = 1) -> TaskProcessingContext:
        return TaskProcessingContext(
            task_id="task-1",
            run_id=run_id,
            team_id=1,
            team_uuid=str(uuid.uuid4()),
            organization_id=str(uuid.uuid4()),
            github_integration_id=github_integration_id,
            repository="org/repo",
            distinct_id="user-1",
        )

    def _run(self, ctx: TaskProcessingContext):
        return get_pr_context(GetPrContextInput(context=ctx))

    @pytest.mark.django_db
    def test_returns_none_when_no_github_integration(self, test_task_run):
        ctx = self._ctx(run_id=str(test_task_run.id), github_integration_id=None)
        assert self._run(ctx) is None

    @pytest.mark.django_db
    def test_returns_none_when_task_run_missing(self):
        ctx = self._ctx(run_id="550e8400-e29b-41d4-a716-446655440000")
        assert self._run(ctx) is None

    @pytest.mark.django_db
    def test_returns_none_when_task_run_has_no_output(self, test_task_run):
        # Default output is None — no pr_url stored yet
        ctx = self._ctx(run_id=str(test_task_run.id))
        assert self._run(ctx) is None

    @pytest.mark.django_db
    def test_returns_none_when_output_has_no_pr_url(self, test_task_run):
        test_task_run.output = {"commit_sha": "abc123"}
        test_task_run.save(update_fields=["output"])

        ctx = self._ctx(run_id=str(test_task_run.id))
        assert self._run(ctx) is None

    @pytest.mark.django_db
    def test_returns_none_when_github_integration_missing(self, test_task_run):
        test_task_run.output = {"pr_url": "https://github.com/org/repo/pull/1"}
        test_task_run.save(update_fields=["output"])

        ctx = self._ctx(run_id=str(test_task_run.id), github_integration_id=999999)
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", side_effect=ObjectDoesNotExist):
            assert self._run(ctx) is None

    @pytest.mark.django_db
    def test_returns_none_when_pull_request_fetch_reports_failure(self, test_task_run):
        test_task_run.output = {"pr_url": "https://github.com/org/repo/pull/1"}
        test_task_run.save(update_fields=["output"])

        integration = MagicMock()
        integration.get_pull_request_from_url.return_value = {"success": False, "error": "not found"}

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
            assert self._run(ctx) is None

    @pytest.mark.django_db
    def test_returns_context_with_fingerprint_on_success(self, test_task_run):
        pr_url = "https://github.com/org/repo/pull/42"
        test_task_run.output = {"pr_url": pr_url}
        test_task_run.save(update_fields=["output"])

        integration = MagicMock()
        integration.get_pull_request_from_url.return_value = {
            "success": True,
            "url": pr_url,
            "state": "open",
            "updated_at": "2026-04-23T10:00:00Z",
        }

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
            result = self._run(ctx)

        assert isinstance(result, GetPrContextOutput)
        assert result.pr_url == pr_url
        assert result.pr_state == "open"
        assert result.fingerprint == compute_pr_fingerprint({"url": pr_url, "updated_at": "2026-04-23T10:00:00Z"})
        integration.get_pull_request_from_url.assert_called_once_with(pr_url)

    @pytest.mark.django_db
    def test_defaults_pr_state_to_unknown_when_missing(self, test_task_run):
        pr_url = "https://github.com/org/repo/pull/1"
        test_task_run.output = {"pr_url": pr_url}
        test_task_run.save(update_fields=["output"])

        integration = MagicMock()
        integration.get_pull_request_from_url.return_value = {
            "success": True,
            "url": pr_url,
            "updated_at": "2026-04-23T10:00:00Z",
        }

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
            result = self._run(ctx)

        assert result is not None
        assert result.pr_state == "unknown"

    @pytest.mark.django_db
    def test_raises_task_invalid_state_when_github_call_raises(self, test_task_run):
        pr_url = "https://github.com/org/repo/pull/1"
        test_task_run.output = {"pr_url": pr_url}
        test_task_run.save(update_fields=["output"])

        integration = MagicMock()
        integration.get_pull_request_from_url.side_effect = RuntimeError("GitHub exploded")

        ctx = self._ctx(run_id=str(test_task_run.id))
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
            with pytest.raises(TaskInvalidStateError):
                self._run(ctx)

    @pytest.mark.django_db
    def test_different_updated_at_yields_different_fingerprint(self, test_task_run):
        # Drives the same invariant as test_ci_follow_up_fires_on_changed_fingerprint_and_persists
        # at the activity level — if upstream GitHub reports a newer updated_at,
        # the workflow must see a new fingerprint and re-fire CI follow-up.
        pr_url = "https://github.com/org/repo/pull/7"
        test_task_run.output = {"pr_url": pr_url}
        test_task_run.save(update_fields=["output"])

        integration = MagicMock()
        ctx = self._ctx(run_id=str(test_task_run.id))

        integration.get_pull_request_from_url.return_value = {
            "success": True,
            "url": pr_url,
            "state": "open",
            "updated_at": "2026-04-23T10:00:00Z",
        }
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
            first = self._run(ctx)

        integration.get_pull_request_from_url.return_value = {
            "success": True,
            "url": pr_url,
            "state": "open",
            "updated_at": "2026-04-23T11:00:00Z",
        }
        with patch(f"{GET_PR_CONTEXT_MODULE}.get_github_integration", return_value=integration):
            second = self._run(ctx)

        assert first is not None and second is not None
        assert first.fingerprint != second.fingerprint


@pytest.mark.requires_secrets
class TestGetGithubIntegration:
    @pytest.mark.django_db
    def test_refreshes_token_when_expired(self, github_integration):
        with (
            patch(f"{GET_PR_CONTEXT_MODULE}.GitHubIntegration") as MockGitHubIntegration,
        ):
            wrapped = MagicMock()
            wrapped.access_token_expired.return_value = True
            MockGitHubIntegration.return_value = wrapped

            result = get_github_integration(github_integration.id)

        assert result is wrapped
        wrapped.access_token_expired.assert_called_once()
        wrapped.refresh_access_token.assert_called_once()

    @pytest.mark.django_db
    def test_does_not_refresh_when_token_valid(self, github_integration):
        with patch(f"{GET_PR_CONTEXT_MODULE}.GitHubIntegration") as MockGitHubIntegration:
            wrapped = MagicMock()
            wrapped.access_token_expired.return_value = False
            MockGitHubIntegration.return_value = wrapped

            result = get_github_integration(github_integration.id)

        assert result is wrapped
        wrapped.refresh_access_token.assert_not_called()

    @pytest.mark.django_db
    def test_raises_when_integration_not_found(self):
        from posthog.models import Integration

        with pytest.raises(Integration.DoesNotExist):
            get_github_integration(999999999)
