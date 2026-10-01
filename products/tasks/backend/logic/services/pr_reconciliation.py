from datetime import datetime
from typing import Literal

from django.db import transaction
from django.utils.dateparse import parse_datetime

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import (
    GitHubIntegrationBase,
    GitHubIntegrationError,
    _is_safe_github_repo_path,
)
from posthog.models.integration import GitHubIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserGitHubIntegration

from products.signals.backend.facade.github import reconcile_pull_request_state
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.pr_urls import read_head_branches, read_pr_urls
from products.tasks.backend.webhooks import _run_repository_filter, _task_run_scope_team_ids, find_task_run

logger = structlog.get_logger(__name__)


@frozen
class PullRequestSnapshot:
    url: str
    head_branch: str
    head_repository: str
    state: Literal["open", "draft", "closed", "merged"]
    merged_at: datetime | None

    @classmethod
    def from_github(cls, response: dict[str, object]) -> "PullRequestSnapshot | None":
        url, branch, repository = response.get("url"), response.get("head_branch"), response.get("head_repository")
        if not all(isinstance(value, str) and value for value in (url, branch, repository)):
            return None
        if response.get("state") not in {"open", "closed"}:
            return None
        assert isinstance(url, str) and isinstance(branch, str) and isinstance(repository, str)
        state: Literal["open", "draft", "closed", "merged"] = "open"
        if response.get("merged") is True:
            state = "merged"
        elif response.get("state") == "closed":
            state = "closed"
        elif response.get("draft") is True:
            state = "draft"
        merged_at = response.get("merged_at")
        return cls(
            url=url,
            head_branch=branch,
            head_repository=repository,
            state=state,
            merged_at=parse_datetime(merged_at) if isinstance(merged_at, str) else None,
        )


class PullRequestReconciler:
    @staticmethod
    def schedule(run: TaskRun, *, previous_output: object, previous_branch: str | None) -> None:
        from products.tasks.backend.tasks.tasks import (  # noqa: PLC0415 - avoids the facade/task import cycle
            reconcile_task_run_pull_request,
        )

        state = run.state if isinstance(run.state, dict) else {}
        verified = state.get("verified_pr_urls") or []
        metadata_changed = run.branch != previous_branch or read_head_branches(run.output) != read_head_branches(
            previous_output
        )
        previous_urls = read_pr_urls(previous_output)
        for url in read_pr_urls(run.output):
            if url in verified or (url in previous_urls and not metadata_changed):
                continue
            if GitHubIntegrationBase.parse_pull_request_url(url) is None:
                continue

            def enqueue(pr_url: str = url) -> None:
                try:
                    reconcile_task_run_pull_request.delay(team_id=run.team_id, run_id=str(run.id), pr_url=pr_url)
                except Exception:
                    logger.exception("task_pr_reconciliation_enqueue_failed", run_id=str(run.id))

            transaction.on_commit(enqueue)

    def __init__(self, *, team_id: int, run_id: str, pr_url: str) -> None:
        self.team_id = team_id
        self.run_id = run_id
        self.pr_url = pr_url

    def _log(self, outcome: str) -> None:
        logger.info("task_pr_reconciliation", team_id=self.team_id, run_id=self.run_id, outcome=outcome)

    def _eligible(self, run: TaskRun) -> bool:
        state = run.state if isinstance(run.state, dict) else {}
        return (
            not run.task.deleted
            and run.task.origin_product != Task.OriginProduct.REVIEW_HOG
            and self.pr_url in read_pr_urls(run.output)
            and self.pr_url not in (state.get("verified_pr_urls") or [])
        )

    @staticmethod
    def _github(run: TaskRun) -> GitHubIntegrationBase | None:
        integration = run.task.github_integration
        if integration is not None and integration.team_id == run.team_id and integration.kind == "github":
            return GitHubIntegration(integration, source="task_pr_reconciliation", priority=Priority.BATCH)
        personal = run.task.github_user_integration
        if (
            personal is not None
            and personal.kind == "github"
            and personal.user_id == run.task.created_by_id
            and OrganizationMembership.objects.filter(
                user_id=personal.user_id, organization_id=run.team.organization_id
            ).exists()
        ):
            return UserGitHubIntegration(personal, source="task_pr_reconciliation", priority=Priority.BATCH)
        return None

    def reconcile(self) -> None:
        parsed = GitHubIntegrationBase.parse_pull_request_url(self.pr_url)
        if (
            parsed is None
            or not _is_safe_github_repo_path(parsed.repository)
            or self.pr_url != f"https://github.com/{parsed.repository}/pull/{parsed.number}"
        ):
            self._log("invalid_url")
            return
        runs = TaskRun.objects.using("default").filter(team_id=self.team_id, id=self.run_id)
        run = (
            runs.filter(_run_repository_filter(parsed.repository))
            .select_related("task__github_integration", "task__github_user_integration", "team")
            .first()
        )
        if run is None or not self._eligible(run):
            self._log("ineligible")
            return
        github = self._github(run)
        if github is None:
            self._log("missing_integration")
            return
        scope = _task_run_scope_team_ids({"installation": {"id": github.github_installation_id}})
        if self.team_id not in scope:
            self._log("outside_installation_scope")
            return
        try:
            response = github.get_pull_request(parsed.repository, parsed.number)
        except GitHubIntegrationError as error:
            if error.status_code in {401, 403, 404}:
                self._log("inaccessible")
                return
            raise
        if not response.get("success"):
            if response.get("status_code") in {401, 403, 404, 422}:
                self._log("inaccessible")
                return
            status_code = response.get("status_code")
            raise GitHubIntegrationError(
                "Could not fetch PR for reconciliation",
                status_code=status_code if isinstance(status_code, int) else None,
            )
        snapshot = PullRequestSnapshot.from_github(response)
        if (
            snapshot is None
            or snapshot.url != self.pr_url
            or snapshot.head_repository.lower() != parsed.repository.lower()
        ):
            self._log("pr_mismatch")
            return
        with transaction.atomic():
            locked = runs.select_for_update(of=("self",)).select_related("task").first()
            if locked is None or not self._eligible(locked):
                self._log("superseded")
                return
            if (
                locked.task.github_integration_id != run.task.github_integration_id
                or locked.task.github_user_integration_id != run.task.github_user_integration_id
                or self._github(locked) is None
            ):
                self._log("integration_changed")
                return
            matched = find_task_run(
                pr_url=self.pr_url, branch=snapshot.head_branch, repository=parsed.repository, team_ids=scope
            )
            if matched is None or matched.id != locked.id:
                self._log("different_run")
                return
            state = locked.state if isinstance(locked.state, dict) else {}
            verified = state.get("verified_pr_urls")
            locked.state = {
                **state,
                "verified_pr_urls": [*(verified if isinstance(verified, list) else []), self.pr_url],
            }
            output = locked.output if isinstance(locked.output, dict) else {}
            if output.get("pr_url") == self.pr_url:
                locked.output = {
                    **output,
                    "pr_state": snapshot.state,
                    "pr_merged": snapshot.state == "merged",
                }
                if snapshot.state == "merged" and "wizard_config" in state:
                    locked.state["reconciled_pr_merge_url"] = self.pr_url
            # Output receivers must retry report linking after verification, even if the URL is unchanged.
            locked.save(update_fields=["state", "output", "updated_at"])
            reconcile_pull_request_state(
                team_id=self.team_id,
                repository=parsed.repository,
                pr_number=parsed.number,
                pr_state=snapshot.state,
                merged_at=snapshot.merged_at,
            )
        self._log("verified")
