"""Analytics for repository and context configuration changes on Spaces and Tasks.

Neither `Channel` nor `Task` carries an activity log, so before these events the only
trace of a repo config change was the row's own `updated_at`. That cannot say who
changed what, from what, to what.

Lives outside `facade/api.py` because both that module and `models.py` emit from here,
and the facade already imports the models.
"""

import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Team, User

logger = structlog.get_logger(__name__)

REPOSITORY_CONFIG_CHANGED = "repository_config_changed"
SPACE_CONTEXT_CHANGED = "space_context_changed"


def _distinct_id(team: Team, user_id: int | None) -> str:
    # Mirrors Task.capture_event: the actor when we have one, else the team.
    if user_id is not None:
        distinct_id = User.objects.filter(id=user_id).values_list("distinct_id", flat=True).first()
        if distinct_id:
            return str(distinct_id)
    return str(team.uuid)


def _normalized(repositories: list[str] | None) -> set[str]:
    return {repo.strip().lower() for repo in (repositories or []) if repo and repo.strip()}


def repositories_differ(left: list[str] | None, right: list[str] | None) -> bool:
    """Whether two repository lists name different repos, ignoring order and case."""
    return _normalized(left) != _normalized(right)


def capture_repository_config_changed(
    *,
    team: Team,
    user_id: int | None,
    subject: str,
    trigger: str,
    previous_repositories: list[str] | None,
    repositories: list[str] | None,
    previous_integration_id: int | None = None,
    integration_id: int | None = None,
    channel_id: str | None = None,
    task_id: str | None = None,
    origin_product: str | None = None,
    space_repositories: list[str] | None = None,
    affected_space_count: int | None = None,
) -> None:
    """Record a repository configuration change on a Space (`subject="space"`) or a
    Task (`subject="task"`).

    Emits nothing when neither the repository set nor the integration actually moved, so
    a PATCH that resubmits the same list stays out of the data. Best-effort: a capture
    failure must never fail the write it describes.
    """
    try:
        previous = _normalized(previous_repositories)
        current = _normalized(repositories)
        integration_changed = previous_integration_id != integration_id
        if previous == current and not integration_changed:
            return

        added = sorted(current - previous)
        removed = sorted(previous - current)
        properties: dict = {
            "subject": subject,
            "trigger": trigger,
            "team_id": team.id,
            "previous_repository_count": len(previous),
            "repository_count": len(current),
            "added_count": len(added),
            "removed_count": len(removed),
            # The delta only. The full list is customer project naming, and the counts
            # above already answer "how often" and "how much".
            "added_repositories": added,
            "removed_repositories": removed,
            "is_first_configuration": not previous and bool(current),
            "is_cleared": bool(previous) and not current,
            "github_integration_changed": integration_changed,
            "github_integration_id": integration_id,
            "previous_github_integration_id": previous_integration_id,
        }
        if channel_id is not None:
            properties["channel_id"] = str(channel_id)
        if task_id is not None:
            properties["task_id"] = str(task_id)
        if origin_product is not None:
            properties["origin_product"] = origin_product
        if affected_space_count is not None:
            properties["affected_space_count"] = affected_space_count
        if subject == "task" and space_repositories is not None:
            space = _normalized(space_repositories)
            properties["space_repository_count"] = len(space)
            properties["diverged_from_space"] = current != space
            # True when this edit is what broke inheritance, as opposed to a task that
            # already sat apart from its Space.
            properties["was_inherited_from_space"] = previous == space

        posthoganalytics.capture(
            distinct_id=_distinct_id(team, user_id),
            event=REPOSITORY_CONFIG_CHANGED,
            properties=properties,
            groups=groups(team=team),
            send_feature_flags=True,
        )
    except Exception as e:
        logger.warning("repository_config_changed.capture_failed", subject=subject, trigger=trigger, error=str(e))


def capture_space_context_changed(
    *,
    team: Team,
    user_id: int | None,
    channel_id: str,
    action: str,
    source: str,
    previous_version: int,
    new_version: int | None = None,
    content_bytes: int = 0,
    previous_content_bytes: int | None = None,
    base_version_provided: bool = False,
    versions_deleted: int | None = None,
) -> None:
    """Record a Space's CONTEXT.md being published or cleared.

    `source` separates people from loops: a loop configured with `update_context`
    republishes on every fire, which outnumbers human edits by orders of magnitude.
    Carries byte counts only — CONTEXT.md is customer-authored free text.
    """
    try:
        properties: dict = {
            "action": action,
            "source": source,
            "team_id": team.id,
            "channel_id": str(channel_id),
            "previous_version": previous_version,
            "new_version": new_version,
            "is_first_version": previous_version == 0 and new_version is not None,
            "content_bytes": content_bytes,
            "previous_content_bytes": previous_content_bytes,
            "base_version_provided": base_version_provided,
        }
        if versions_deleted is not None:
            properties["versions_deleted"] = versions_deleted

        posthoganalytics.capture(
            distinct_id=_distinct_id(team, user_id),
            event=SPACE_CONTEXT_CHANGED,
            properties=properties,
            groups=groups(team=team),
            send_feature_flags=True,
        )
    except Exception as e:
        logger.warning("space_context_changed.capture_failed", action=action, error=str(e))
