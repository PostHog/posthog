from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.user_integration import UserGitHubIntegration

from products.tasks.backend.models import Task


def task_review(team_id: int, task_id: str, user_id: int, page: int) -> dict:
    task = (
        Task.objects.filter(team_id=team_id, id=task_id, created_by_id=user_id, deleted=False)
        .select_related("github_integration", "github_user_integration")
        .first()
    )
    if task is None:
        raise NotFound()
    run = task.runs.order_by("-created_at").first()
    url = (run.output or {}).get("pr_url") if run else None
    parsed = GitHubIntegration.parse_pull_request_url(url) if isinstance(url, str) else None
    if parsed is None:
        raise NotFound("This task has no pull request yet.")
    repositories = {repo.lower() for repo in [task.repository, *(task.repositories or [])] if repo}
    if parsed.repository.lower() not in repositories:
        raise PermissionDenied("The pull request is outside this task's repositories.")
    github: GitHubIntegration | UserGitHubIntegration
    if task.github_user_integration_id and task.github_user_integration.user_id == user_id:
        github = UserGitHubIntegration(task.github_user_integration)
    else:
        integrations = Integration.objects.filter(team_id=team_id, kind="github")
        integration = integrations.filter(id=task.github_integration_id).first() if task.github_integration_id else None
        if integration is None:
            raise ValidationError("Connect GitHub in PostHog to load the review.")
        github = GitHubIntegration(integration)
        if github.access_token_expired():
            github.refresh_access_token()
    snapshot = github.get_pull_request_snapshot(url)
    if not snapshot.get("success"):
        raise ValidationError("Could not load this pull request. Open it in GitHub or try again.")
    response = github.api_request(
        "GET",
        f"/repos/{parsed.repository}/pulls/{parsed.number}/files",
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/files",
        params={"per_page": 30, "page": page},
    )
    if response.status_code != 200:
        raise ValidationError("Could not load changed files. Open them in GitHub or try again.")
    files = []
    for item in response.json():
        patch = item.get("patch") or ""
        files.append(
            {
                "filename": item["filename"],
                "status": item["status"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "patch": patch[:20000],
                "truncated": len(patch) > 20000 or not patch,
            }
        )
    return {
        "url": url,
        "title": snapshot.get("title") or "Pull request",
        "state": snapshot.get("state") or "unknown",
        "ci_status": snapshot.get("ci_status") or "none",
        "head_sha": snapshot.get("head_sha") or "",
        "files": files,
        "has_more": 'rel="next"' in response.headers.get("Link", ""),
    }
