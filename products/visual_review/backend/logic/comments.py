"""Posting and updating the visual-review comment on a PR."""

from __future__ import annotations

from uuid import UUID

import structlog

from posthog.egress.github.transport import GitHubRateLimitError

from ..db import WRITER_DB
from ..facade.enums import ReviewDecision, RunPurpose
from ..models import Repo, Run
from . import comment_markdown, github_api, run_queries

logger = structlog.get_logger(__name__)


def _comment_id(run: Run) -> int | None:
    """The GitHub comment ID stored on a run, if it has one."""
    value = run.metadata.get("github_comment_id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _previous_comment(repo: Repo, pr_number: int, run_type: str, exclude_run_id: UUID) -> tuple[Run, int] | None:
    """The run of this run type that owns its live visual-review comment, and that comment's ID.

    Scoped to the run type because supersession and the commit status are: a PR can carry
    an active run per run type, each with its own gate and its own approval, so another
    type's prompt is still waiting for an answer and must not be retired.

    Reads the writer: ``review_decision`` decides whether the comment is rewritten or
    deleted, and a replica that still reports the pre-approval value would delete a
    comment that records a human decision.
    """
    previous_run = (
        Run.objects.using(WRITER_DB)
        .filter(repo=repo, pr_number=pr_number, run_type=run_type, metadata__has_key="github_comment_id")
        .exclude(id=exclude_run_id)
        .order_by("-created_at")
        .first()
    )
    if previous_run is None:
        return None
    comment_id = _comment_id(previous_run)
    return (previous_run, comment_id) if comment_id is not None else None


def _retire_previous_comment(repo: Repo, previous_run: Run, comment_id: int) -> None:
    """Clear the previous run's comment of this run type out of the way once a new one is posted.

    An approval comment records a human decision, so it stays and says which revision
    it covered. An unanswered review prompt holds nothing worth keeping, so it goes.
    Best-effort: a failure here only leaves an extra comment on the PR.
    """
    if previous_run.review_decision == ReviewDecision.HUMAN_APPROVED:
        approver = comment_markdown._resolve_approver(previous_run.approved_by_id)
        response = github_api._github_api_request(
            method="PATCH",
            repo=repo,
            path=f"issues/comments/{comment_id}",
            json={"body": comment_markdown._build_superseded_approval_body(previous_run, repo, approver)},
        )
        retired = response.status_code == 200
    else:
        response = github_api._github_api_request(method="DELETE", repo=repo, path=f"issues/comments/{comment_id}")
        retired = response.status_code in (204, 404)

    if not retired:
        logger.info(
            "visual_review.previous_pr_comment_not_retired",
            run_id=str(previous_run.id),
            comment_id=comment_id,
            status_code=response.status_code,
        )


def _post_review_prompt_comment(run: Run, repo: Repo) -> None:
    """
    Post a PR comment prompting reviewers to approve visual changes.

    Every run that needs review posts its own comment, so GitHub notifies the
    reviewers and the prompt sits at the bottom of the PR with the new changes.
    The previous run's comment is retired after the new one lands, to keep one live
    prompt per run type. Retiring first would leave the PR with no prompt at all when
    the post then fails.
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

    comment_body = comment_markdown._build_review_prompt_body(run, repo)
    previous: tuple[Run, int] | None = None

    try:
        previous = _previous_comment(repo, run.pr_number, run.run_type, exclude_run_id=run.id)

        response = github_api._github_api_request(
            method="POST",
            repo=repo,
            path=f"issues/{run.pr_number}/comments",
            json={"body": comment_body},
        )
        if response.status_code != 201:
            logger.warning(
                "visual_review.pr_comment_failed",
                run_id=str(run.id),
                pr_number=run.pr_number,
                status_code=response.status_code,
                response=response.text[:200],
            )
            return

        comment_id = response.json().get("id")
        run.metadata["github_comment_id"] = comment_id
        run.save(update_fields=["metadata"])
    except Exception:
        logger.warning("visual_review.pr_comment_error", run_id=str(run.id), pr_number=run.pr_number, exc_info=True)
        return

    if previous is None:
        return

    try:
        _retire_previous_comment(repo, *previous)
    except Exception:
        logger.warning(
            "visual_review.previous_pr_comment_retire_error",
            run_id=str(previous[0].id),
            comment_id=previous[1],
            exc_info=True,
        )


def _post_approval_comment(run: Run, repo: Repo, add_images: bool = False) -> None:
    """Report an approval on the PR, as an update of this run's own review prompt.

    Falls back to a new comment when the prompt is gone or was never posted, so an
    approval is always visible on the PR. ``add_images`` embeds the before/after
    snapshot images in the comment when the reviewer opted in. Best-effort and
    never raises.
    """
    if not repo.enable_pr_comments:
        return

    if not repo.repo_full_name or run.pr_number is None:
        return

    if run.review_decision != ReviewDecision.HUMAN_APPROVED:
        return

    approver = comment_markdown._resolve_approver(run.approved_by_id)
    body = comment_markdown._build_approval_comment_body(run, repo, approver, add_images=add_images)
    comment_id = _comment_id(run)

    try:
        if comment_id is not None:
            response = github_api._github_api_request(
                method="PATCH",
                repo=repo,
                path=f"issues/comments/{comment_id}",
                json={"body": body},
                timeout=15,
            )
            if response.status_code == 200:
                return

            # Anything but a missing comment is not fixed by posting a second one.
            if response.status_code != 404:
                logger.warning(
                    "visual_review.approval_comment_update_failed",
                    run_id=str(run.id),
                    comment_id=comment_id,
                    status_code=response.status_code,
                    response=response.text[:200],
                )
                return

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
    """Public entrypoint for the Celery task to update a PR comment after approval.

    Reads the writer: ``finalize_run`` queues this task on commit, so a replica that
    still reports the pre-approval ``review_decision`` makes the post silently skip,
    and nothing retries it.
    """
    run = (
        Run.objects.select_related("repo")
        .using(WRITER_DB)
        .filter(id=run_id, **({"team_id": team_id} if team_id is not None else {}))
        .first()
    )
    if run is None:
        return
    _post_approval_comment(run, run.repo, add_images=add_images)
