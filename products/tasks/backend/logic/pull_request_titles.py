from uuid import UUID

from django.core.cache import cache

import structlog

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.models.github_integration_base import GitHubIntegrationError, PullRequestRef
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.user_integration import UserGitHubIntegration

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.pr_urls import read_pr_urls
from products.tasks.backend.visibility import task_visibility_q

logger = structlog.get_logger(__name__)

_MAX_PULL_REQUESTS = 50
_CACHE_TTL_SECONDS = 60 * 60


def _cache_key(team_id: int, url: str) -> str:
    return f"tasks:pr_title:{team_id}:{url}"


def _pull_request_url(ref: PullRequestRef) -> str:
    return f"https://github.com/{ref.repository}/pull/{ref.number}"


def _fetch_titles(github: GitHubIntegration | UserGitHubIntegration, refs: list[PullRequestRef]) -> dict[str, str]:
    declarations: list[str] = []
    fields: list[str] = []
    variables: dict[str, str | int] = {}
    for index, ref in enumerate(refs):
        declarations.append(f"$owner{index}: String!, $repo{index}: String!, $number{index}: Int!")
        fields.append(
            f"pr{index}: repository(owner: $owner{index}, name: $repo{index}) "
            f"{{ pullRequest(number: $number{index}) {{ title }} }}"
        )
        variables.update({f"owner{index}": ref.owner, f"repo{index}": ref.repo, f"number{index}": ref.number})
    query = f"query({', '.join(declarations)}) {{ {' '.join(fields)} }}"
    data = github._gh_graphql(query, variables, endpoint="/graphql:pullRequestTitles")
    titles: dict[str, str] = {}
    for index, ref in enumerate(refs):
        pull_request = (data.get(f"pr{index}") or {}).get("pullRequest") or {}
        titles[_pull_request_url(ref)] = pull_request.get("title") or ""
    return titles


def _integration_key(task: Task, user_id: int) -> tuple[str, int | str]:
    user_integration = task.github_user_integration
    if user_integration is not None and user_integration.user_id == user_id:
        return ("user", str(user_integration.id))
    return ("team", task.github_integration_id or 0)


def _github_for_task(task: Task, team_id: int, user_id: int) -> GitHubIntegration | UserGitHubIntegration | None:
    user_integration = task.github_user_integration
    if user_integration is not None and user_integration.user_id == user_id:
        return UserGitHubIntegration(user_integration)
    if not task.github_integration_id:
        return None
    integration = Integration.objects.filter(team_id=team_id, kind="github", id=task.github_integration_id).first()
    if integration is None:
        return None
    github = GitHubIntegration(integration)
    if github.access_token_expired():
        github.refresh_access_token()
    return github


def pull_request_titles(team_id: int, user_id: int, task_ids: list[UUID]) -> dict[str, str]:
    tasks = {
        str(task.id): task
        for task in Task.objects.filter(team_id=team_id, deleted=False, id__in=task_ids)
        .filter(task_visibility_q(user_id))
        .select_related("github_user_integration")
    }
    latest_outputs = (
        TaskRun.objects.filter(team_id=team_id, task_id__in=tasks.keys())
        .order_by("task_id", "-created_at", "-id")
        .distinct("task_id")
        .values_list("task_id", "output")
    )
    refs_by_task: dict[str, list[PullRequestRef]] = {}
    for task_id, output in latest_outputs:
        task = tasks[str(task_id)]
        repositories = {repo.lower() for repo in [task.repository, *(task.repositories or [])] if repo}
        for url in read_pr_urls(output):
            ref = GitHubIntegration.parse_pull_request_url(url)
            if ref is not None and ref.repository.lower() in repositories:
                refs_by_task.setdefault(str(task_id), []).append(ref)

    urls = list(dict.fromkeys(_pull_request_url(ref) for refs in refs_by_task.values() for ref in refs))
    cached = cache.get_many([_cache_key(team_id, url) for url in urls])
    titles = {url: cached[_cache_key(team_id, url)] for url in urls if _cache_key(team_id, url) in cached}

    missing_by_integration: dict[tuple[str, int | str], list[PullRequestRef]] = {}
    tasks_by_integration: dict[tuple[str, int | str], Task] = {}
    queued: set[str] = set()
    for task_key, refs in refs_by_task.items():
        task = tasks[task_key]
        integration_key = _integration_key(task, user_id)
        for ref in refs:
            url = _pull_request_url(ref)
            if url in titles or url in queued or len(queued) >= _MAX_PULL_REQUESTS:
                continue
            queued.add(url)
            missing_by_integration.setdefault(integration_key, []).append(ref)
            tasks_by_integration.setdefault(integration_key, task)

    for integration_key, refs in missing_by_integration.items():
        try:
            github = _github_for_task(tasks_by_integration[integration_key], team_id, user_id)
            if github is None:
                continue
            fetched = _fetch_titles(github, refs)
        except (GitHubIntegrationError, GitHubRateLimitError, GitHubEgressBudgetExhausted):
            logger.warning("tasks_pull_request_titles_fetch_failed", team_id=team_id, exc_info=True)
            continue
        cache.set_many({_cache_key(team_id, url): title for url, title in fetched.items()}, _CACHE_TTL_SECONDS)
        titles.update(fetched)

    return {url: title for url, title in titles.items() if title}
