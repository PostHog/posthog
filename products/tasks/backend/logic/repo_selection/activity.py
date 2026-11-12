"""Size, file type, and activity figures for the candidate lines of the repository selection prompt.

The figures let the selector tell the repository where people work apart from a mirror or export
with the same file tree, a repository only a bot writes to, and a stale side project. They are
hints: a candidate without figures renders with its visibility only, and selection never waits
for GitHub to produce them.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection, Mapping

from django.utils import timezone

from posthog import redis as posthog_redis
from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration
from posthog.models.integration_repository_cache import (
    ACTIVITY_AUTHOR_SAMPLE,
    GitHubRepositoryFullCache,
    activity_refresh_due,
)
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

logger = logging.getLogger(__name__)

# Distinct authors are counted over the last `ACTIVITY_AUTHOR_SAMPLE` commits, so a busy repository
# reaches this count however many people work in it. The prompt renders it as a floor (`25+`).
AUTHOR_COUNT_FLOOR = 25

# Concurrent selections for one source enqueue one refresh. A refresh that fails leaves its rows due,
# so this also spaces out the retries.
ACTIVITY_REFRESH_ENQUEUE_TTL_SECONDS = 60 * 60
_ENQUEUE_KEY_PREFIX = "repo_selection:activity_refresh"

ACTIVITY_PROMPT_GUIDE = f"""Listed most active first. Each line gives the visibility and, when known, the size and main
file types, the commits on the default branch in the last 30 days and how many people made the
last {ACTIVITY_AUTHOR_SAMPLE} commits, and the merged pull requests of all time. The figures are approximate and may
be days old, and the order is a hint, not a ranking of relevance. Merged pull requests show where
people review and land work. A repository with many commits but almost no merged pull requests,
or with one author, is usually a mirror, an export, or a bot target: select it only on specific
evidence that the work belongs there. `same files as` marks a repository whose file tree equals
another candidate's; the one with more merged pull requests is usually the source."""


@frozen
class RepositoryFigures:
    file_count: int | None = None
    tree_truncated: bool = False
    top_extensions: tuple[str, ...] = ()
    tree_hash: str | None = None
    commits_last_30_days: int | None = None
    recent_author_count: int | None = None
    merged_pull_request_count: int | None = None


def load_candidate_figures(
    github: GitHubIntegrationBase, team_id: int, candidates: Collection[str]
) -> dict[str, RepositoryFigures]:
    """The stored figures of each candidate, read without a GitHub call.

    Enqueues a background refresh when a candidate's figures are missing or past the refresh
    interval. Any failure returns no figures, which renders every candidate as visibility only.
    """
    try:
        entries = list(
            github.integration.repository_cache_entries.filter(team_id=team_id, full_name__in=list(candidates)).only(
                "full_name",
                "tree_truncated",
                "file_count",
                "top_extensions",
                "tree_hash",
                "commits_last_30_days",
                "recent_author_count",
                "merged_pull_request_count",
                "activity_updated_at",
            )
        )
    except Exception:
        logger.warning("repo_selection.figures_read_failed", extra={"team_id": team_id}, exc_info=True)
        return {}
    now = timezone.now()
    if any(activity_refresh_due(entry, now) for entry in entries):
        enqueue_activity_refresh(github, team_id)
    return {
        entry.full_name: RepositoryFigures(
            file_count=entry.file_count,
            tree_truncated=entry.tree_truncated,
            top_extensions=tuple(extension for extension in entry.top_extensions or [] if isinstance(extension, str)),
            tree_hash=entry.tree_hash,
            commits_last_30_days=entry.commits_last_30_days,
            recent_author_count=entry.recent_author_count,
            merged_pull_request_count=entry.merged_pull_request_count,
        )
        for entry in entries
    }


def _source_ids(github: GitHubIntegrationBase) -> dict[str, int | str]:
    if isinstance(github, UserGitHubIntegration):
        return {"user_integration_id": str(github.integration.id)}
    return {"integration_id": github.integration.id}


def enqueue_activity_refresh(github: GitHubIntegrationBase, team_id: int) -> None:
    """Start `refresh_repository_activity` for this source, at most once per enqueue window. Never raises."""
    from products.tasks.backend.tasks.tasks import (  # noqa: PLC0415 - avoids the facade/task import cycle
        refresh_repository_activity,
    )

    source_ids = _source_ids(github)
    key = ":".join([_ENQUEUE_KEY_PREFIX, *(f"{name}={value}" for name, value in source_ids.items()), str(team_id)])
    try:
        if not posthog_redis.get_client().set(key, "1", nx=True, ex=ACTIVITY_REFRESH_ENQUEUE_TTL_SECONDS):
            return
        refresh_repository_activity.delay(team_id=team_id, **source_ids)
    except Exception:
        logger.warning("repo_selection.activity_refresh_enqueue_failed", extra={"team_id": team_id}, exc_info=True)


def refresh_repository_activity_for_source(
    *, team_id: int, integration_id: int | None, user_integration_id: str | None
) -> None:
    """Refresh the stored figures of one GitHub source's repositories on the batch egress lane."""
    github: GitHubIntegrationBase
    if integration_id is not None:
        try:
            record = IntegrationManager.github.oauth.get(team_id, integration_id)
        except IntegrationNotFound:
            return
        github = GitHubIntegration(record, source="repo_selection_activity", priority=Priority.BATCH)
    elif user_integration_id is not None:
        user_integration = UserIntegration.objects.filter(
            id=user_integration_id, kind=UserIntegration.IntegrationKind.GITHUB
        ).first()
        if user_integration is None:
            return
        github = UserGitHubIntegration(user_integration, source="repo_selection_activity", priority=Priority.BATCH)
    else:
        return
    GitHubRepositoryFullCache(github, team_id=team_id, priority=Priority.BATCH).refresh_activity()


def _recent_authors(figures: RepositoryFigures) -> int:
    # The author sample spans the last commits however old they are, so a repository with no
    # commit in the window has no recent authors.
    if not figures.commits_last_30_days or figures.recent_author_count is None:
        return 0
    return min(figures.recent_author_count, AUTHOR_COUNT_FLOOR)


def _has_activity(figures: RepositoryFigures | None) -> bool:
    return figures is not None and (
        figures.recent_author_count is not None or figures.merged_pull_request_count is not None
    )


@frozen(order=True)
class _ActivityRank:
    # Dataclass ordering compares fields in declaration order, so this order is the sort order.
    no_activity: bool
    fewer_recent_authors: int
    fewer_merged_pull_requests: int
    name: str


def _activity_rank(repo: str, figures: RepositoryFigures | None) -> _ActivityRank:
    if figures is None or not _has_activity(figures):
        return _ActivityRank(no_activity=True, fewer_recent_authors=0, fewer_merged_pull_requests=0, name=repo)
    return _ActivityRank(
        no_activity=False,
        fewer_recent_authors=-_recent_authors(figures),
        fewer_merged_pull_requests=-(figures.merged_pull_request_count or 0),
        name=repo,
    )


def order_by_activity(candidates: Collection[str], figures: Mapping[str, RepositoryFigures]) -> list[str]:
    """Most recent authors first, then most merged pull requests. Candidates without activity go last, by name.

    Author counts are capped at the floor the prompt renders, so two busy repositories with the
    same tree, such as a source and its mirror, are ordered by merged pull requests.
    """
    return sorted(candidates, key=lambda repo: _activity_rank(repo, figures.get(repo)))


def _merged_or_unknown(figures: RepositoryFigures) -> int:
    return -1 if figures.merged_pull_request_count is None else figures.merged_pull_request_count


def same_tree_sources(candidates: Collection[str], figures: Mapping[str, RepositoryFigures]) -> dict[str, str]:
    """Maps each candidate whose file tree equals another candidate's to the one with the most merged pull requests."""
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for repo in candidates:
        repo_figures = figures.get(repo)
        if repo_figures is not None and repo_figures.tree_hash:
            groups[repo_figures.tree_hash].append(repo)
    sources: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        # `max` keeps the first of equal counts, so a tie goes to the more active candidate.
        source = max(order_by_activity(members, figures), key=lambda repo: _merged_or_unknown(figures[repo]))
        sources.update({repo: source for repo in members if repo != source})
    return sources


def approximate(count: int) -> str:
    """Two significant figures, so a line changes rarely and does not suggest precision."""
    if count < 100:
        return str(count)
    return f"~{round(count, 2 - len(str(count))):,}"


def describe_figures(figures: RepositoryFigures | None, same_files_as: str | None = None) -> list[str]:
    """The figure parts of one candidate line, in the order the prompt explains them."""
    parts: list[str] = []
    if figures is not None and figures.file_count is not None:
        if figures.tree_truncated:
            files = f"{approximate(figures.file_count).lstrip('~')}+ files"
        else:
            files = f"{approximate(figures.file_count)} file{'' if figures.file_count == 1 else 's'}"
        if figures.top_extensions:
            files += ": " + ", ".join(figures.top_extensions)
        parts.append(files)
    if figures is not None and figures.commits_last_30_days is not None:
        commits = figures.commits_last_30_days
        text = f"{approximate(commits)} commit{'' if commits == 1 else 's'} in 30 days"
        authors = figures.recent_author_count
        if commits and authors:
            if authors >= AUTHOR_COUNT_FLOOR:
                text += f" by {AUTHOR_COUNT_FLOOR}+ people"
            else:
                text += f" by {authors} {'person' if authors == 1 else 'people'}"
        parts.append(text)
    if figures is not None and figures.merged_pull_request_count is not None:
        merged = figures.merged_pull_request_count
        parts.append(f"{approximate(merged)} merged PR{'' if merged == 1 else 's'}")
    if same_files_as is not None:
        parts.append(f"same files as `{same_files_as}`")
    return parts
