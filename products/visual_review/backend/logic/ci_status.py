"""The GitHub side of the CI gate: commit statuses and job reruns."""

from __future__ import annotations

import structlog

from ..facade.enums import RunPurpose
from ..models import Repo, Run
from . import comment_markdown, github_api

logger = structlog.get_logger(__name__)


def _rerun_github_job(run: Run, check_run_id: str) -> tuple[bool, str | None]:
    """Rerun the visual-review CI job by its numeric ID. Returns (success, error_message).

    The job ID and workflow run ID both come from client-supplied run metadata
    (the CI runner has no server-verified channel today), so before calling
    GitHub we bind the rerun two ways: the job must run on this run's commit
    (``head_sha``) and must belong to the workflow run recorded at creation
    (``github_run_id``). That pins recompute to the workflow run that produced
    this visual-review run instead of letting it re-trigger any job on the
    commit. It is defense-in-depth, not an identity proof — a caller who forges
    a self-consistent metadata set can still reach sibling jobs of that run.
    """
    if not check_run_id.isdigit():
        return False, "Invalid check run ID"

    repo = run.repo
    if not repo.repo_full_name:
        return False, "Repo has no GitHub full name configured"

    expected_run_id = (run.metadata or {}).get("github_run_id")
    if not expected_run_id:
        return False, "Workflow run ID not recorded for this run"

    # `${{ job.check_run_id }}` doubles as the Actions job ID, so the jobs API
    # gives us head_sha and the owning workflow run (run_id) in one call.
    try:
        job_response = github_api._github_api_request("GET", repo, f"actions/jobs/{check_run_id}")
    except Exception:
        return False, "Failed to verify CI job ownership"

    if job_response.status_code != 200:
        return False, f"Could not fetch CI job details (status {job_response.status_code})"

    try:
        job_data = job_response.json()
    except Exception:
        return False, "Failed to parse CI job response"

    if job_data.get("head_sha") != run.commit_sha:
        logger.warning(
            "visual_review.ci_rerun_sha_mismatch",
            run_id=str(run.id),
            check_run_id=check_run_id,
            expected_sha=run.commit_sha,
            actual_sha=job_data.get("head_sha"),
        )
        return False, "Check run does not belong to this commit"

    if str(job_data.get("run_id")) != str(expected_run_id):
        logger.warning(
            "visual_review.ci_rerun_workflow_mismatch",
            run_id=str(run.id),
            check_run_id=check_run_id,
            expected_workflow_run=str(expected_run_id),
            actual_workflow_run=str(job_data.get("run_id")),
        )
        return False, "CI job does not belong to this run's workflow"

    try:
        response = github_api._github_api_request("POST", repo, f"actions/jobs/{check_run_id}/rerun")
    except Exception:
        return False, "Failed to trigger job rerun"

    if response.status_code == 201:
        logger.info(
            "visual_review.ci_job_rerun_triggered",
            run_id=str(run.id),
            check_run_id=check_run_id,
        )
        return True, None

    return False, f"GitHub API returned {response.status_code} when rerunning job"


def _post_commit_status(
    run: Run,
    repo: Repo,
    state: str,
    description: str,
) -> None:
    """
    Post a commit status to GitHub (best-effort, never raises).

    Uses the GitHub Commit Statuses API:
    POST /repos/{owner}/{repo}/statuses/{sha}

    state: "pending", "success", "failure", "error"

    Partial runs (is_partial, client-supplied) suppress removed-baseline
    detection on PR branches, so they must not be able to satisfy the gating
    status context that branch protection evaluates. Branch protection keys off
    the (context, state) pair, not the human-facing description, so a partial
    run is posted to a separate "PostHog Visual Review / {run_type} (partial)"
    context rather than the gating "PostHog Visual Review / {run_type}" one.
    A subset run therefore can never turn the gated context green; a reviewer
    must require the partial context explicitly to gate on partial runs. The
    description is also annotated so the disclosure is visible to humans.
    """
    if not repo.repo_full_name:
        return

    context = f"PostHog Visual Review / {run.run_type}"
    # Tracking-only (observe) and partial runs must never satisfy the gating context that
    # branch protection evaluates. Both purpose and is_partial are client-supplied, so an
    # observe run posted to the gating context could green a PR head SHA's required check
    # without review. Route them to a distinct, non-gating context instead.
    if run.purpose == RunPurpose.OBSERVE:
        context = f"{context} (tracking)"
    elif run.is_partial:
        context = f"{context} (partial)"
        description = f"{description} (partial run)"

    try:
        github = github_api.get_github_integration_for_repo(repo)
    except Exception:
        logger.debug("visual_review.status_check_skipped", run_id=str(run.id), reason="no_github_integration")
        return

    target_url = comment_markdown._run_url(run, repo)

    try:
        response = github.api_request(
            "POST",
            f"/repos/{repo.repo_full_name}/statuses/{run.commit_sha}",
            json_body={
                "state": state,
                "description": description[:140],
                "context": context,
                "target_url": target_url,
            },
        )

        if response.status_code != 201:
            logger.warning(
                "visual_review.status_check_failed",
                run_id=str(run.id),
                status_code=response.status_code,
                response=response.text[:200],
            )
    except Exception:
        logger.warning("visual_review.status_check_error", run_id=str(run.id), exc_info=True)
