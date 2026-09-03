"""Posting and updating the one visual-review comment per PR."""

from __future__ import annotations

from uuid import UUID

import structlog

from posthog.egress.github.transport import GitHubRateLimitError

from ..db import READER_DB, WRITER_DB
from ..facade.enums import ReviewDecision, RunPurpose
from ..models import Repo, Run
from . import comment_markdown, github_api, run_queries

logger = structlog.get_logger(__name__)


def _find_existing_comment_id(repo: Repo, pr_number: int, exclude_run_id: UUID) -> int | None:
    """Find the GitHub comment ID from a previous run on the same PR."""
    previous_run = (
        Run.objects.filter(repo=repo, pr_number=pr_number, metadata__has_key="github_comment_id")
        .exclude(id=exclude_run_id)
        .order_by("-created_at")
        .first()
    )
    if previous_run:
        value = previous_run.metadata.get("github_comment_id")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _post_review_prompt_comment(run: Run, repo: Repo) -> None:
    """
    Post or update a PR comment prompting reviewers to approve visual changes.

    One comment per PR — subsequent runs update the existing comment in place.
    Skips non-actionable runs (observe-only, stale/superseded, already commented).
    Best-effort and never raises.
    """
    if not repo.enable_pr_comments:
        return

    if not repo.repo_full_name or run.pr_number is None:
        return

    if run.purpose == RunPurpose.OBSERVE or run_queries.is_run_stale(run):
        return

    if run.metadata.get("github_comment_id"):
        return

    run_url = comment_markdown._run_url(run, repo)
    comment_body = (
        f"👋 **Visual changes detected** for this PR.\n\n"
        f"[Review and approve in PostHog Visual Review]({run_url})\n\n"
        f"If these changes are unexpected, they may be caused by a flaky test or a "
        f"broken snapshot on master. Don't approve — rerun the job or wait for a fix."
    )

    try:
        existing_comment_id = _find_existing_comment_id(repo, run.pr_number, exclude_run_id=run.id)
        if existing_comment_id:
            response = github_api._github_api_request(
                method="PATCH",
                repo=repo,
                path=f"issues/comments/{existing_comment_id}",
                json={"body": comment_body},
            )
            if response.status_code == 200:
                run.metadata["github_comment_id"] = existing_comment_id
                run.save(update_fields=["metadata"])
                return
            # Comment was deleted or inaccessible — fall through to create new one
            logger.info(
                "visual_review.pr_comment_update_failed_will_create",
                run_id=str(run.id),
                comment_id=existing_comment_id,
                status_code=response.status_code,
            )

        response = github_api._github_api_request(
            method="POST",
            repo=repo,
            path=f"issues/{run.pr_number}/comments",
            json={"body": comment_body},
        )
        if response.status_code == 201:
            comment_id = response.json().get("id")
            run.metadata["github_comment_id"] = comment_id
            run.save(update_fields=["metadata"])
        else:
            logger.warning(
                "visual_review.pr_comment_failed",
                run_id=str(run.id),
                pr_number=run.pr_number,
                status_code=response.status_code,
                response=response.text[:200],
            )
    except Exception:
        logger.warning("visual_review.pr_comment_error", run_id=str(run.id), pr_number=run.pr_number, exc_info=True)


def _post_approval_comment(run: Run, repo: Repo, add_images: bool = False) -> None:
    """Update the existing PR comment in place with the approved-changes summary.

    Best-effort and never raises. Skips silently when the original review-prompt
    comment was never posted (no `github_comment_id` in run.metadata) — i.e.,
    when the review wasn't initiated by a human. ``add_images`` embeds the
    before/after snapshot images in the comment when the reviewer opted in.
    """
    if not repo.enable_pr_comments:
        return

    if not repo.repo_full_name or run.pr_number is None:
        return

    if run.review_decision != ReviewDecision.HUMAN_APPROVED:
        return

    comment_id = run.metadata.get("github_comment_id")
    if not comment_id:
        return
    if isinstance(comment_id, str) and comment_id.isdigit():
        comment_id = int(comment_id)
    if not isinstance(comment_id, int):
        return

    approver = comment_markdown._resolve_approver(run.approved_by_id)
    body = comment_markdown._build_approval_comment_body(run, repo, approver, add_images=add_images)

    try:
        response = github_api._github_api_request(
            method="PATCH",
            repo=repo,
            path=f"issues/comments/{comment_id}",
            json={"body": body},
            timeout=15,
        )
        if response.status_code == 200:
            return

        # Comment was deleted or inaccessible — fall back to creating a new one
        if response.status_code == 404:
            create_response = github_api._github_api_request(
                method="POST",
                repo=repo,
                path=f"issues/{run.pr_number}/comments",
                json={"body": body},
                timeout=15,
            )
            if create_response.status_code == 201:
                new_comment_id = create_response.json().get("id")
                if isinstance(new_comment_id, int):
                    run.metadata["github_comment_id"] = new_comment_id
                    run.save(update_fields=["metadata"], using=WRITER_DB)
                return
            logger.warning(
                "visual_review.approval_comment_create_failed",
                run_id=str(run.id),
                pr_number=run.pr_number,
                status_code=create_response.status_code,
                response=create_response.text[:200],
            )
            return

        logger.warning(
            "visual_review.approval_comment_update_failed",
            run_id=str(run.id),
            comment_id=comment_id,
            status_code=response.status_code,
            response=response.text[:200],
        )
    except GitHubRateLimitError:
        # Bubble up so the Celery task can retry with the suggested countdown.
        raise
    except Exception:
        logger.warning(
            "visual_review.approval_comment_error",
            run_id=str(run.id),
            pr_number=run.pr_number,
            exc_info=True,
        )


def post_approval_comment_for_run(run_id: UUID, team_id: int | None = None, add_images: bool = False) -> None:
    """Public entrypoint for the Celery task to update a PR comment after approval."""
    run = (
        Run.objects.select_related("repo")
        .using(READER_DB)
        .filter(id=run_id, **({"team_id": team_id} if team_id is not None else {}))
        .first()
    )
    if run is None:
        return
    _post_approval_comment(run, run.repo, add_images=add_images)
