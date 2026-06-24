"""Slack App Home tab for the PostHog coding agent.

The Home tab is a per-user surface we can refresh silently with ``views.publish``
(no thread reply, no mention, no Activity-feed entry). It shows the tasks a Slack
user is involved in — ones they started by @-mentioning the bot, or ones they
replied into ("multiplayer"). Involvement is recorded on
``SlackThreadTaskMapping.participant_slack_user_ids``.

This module owns: gathering the involved tasks (from slack_app's own mapping
table, joined to the tasks product *only* through its facade) and rendering +
publishing the Block Kit view.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from posthog.models.integration import Integration, SlackIntegration
from posthog.utils import absolute_uri

from products.slack_app.backend.models import SlackThreadTaskMapping

logger = logging.getLogger(__name__)

# How many recent involved tasks to render. The Home tab is a glanceable summary,
# not a full task list — the "Open in PostHog" links lead to the complete history.
_MAX_TASKS = 25

# Statuses that mean the task is still working. Everything else is terminal and
# shown under "Recently finished".
_ACTIVE_STATUSES = frozenset({"NOT_STARTED", "QUEUED", "IN_PROGRESS"})


@dataclass(frozen=True)
class HomeTabTask:
    """One row on the Home tab — a task the viewing Slack user is involved in."""

    task_id: str
    team_id: int
    title: str
    repository: str | None
    status: str
    stage: str | None
    pr_url: str | None
    error_message: str | None
    sort_key: datetime

    @property
    def is_active(self) -> bool:
        return (self.status or "").upper() in _ACTIVE_STATUSES

    @property
    def task_url(self) -> str:
        return absolute_uri(f"/project/{self.team_id}/tasks/{self.task_id}")


def _status_emoji(task: HomeTabTask) -> str:
    status = (task.status or "").upper()
    if status in _ACTIVE_STATUSES:
        return ":arrows_counterclockwise:"
    if status == "FAILED":
        return ":x:"
    if status == "CANCELLED":
        return ":no_entry_sign:"
    # Completed — a rocket if it produced a PR, otherwise the hedgehog.
    return ":rocket:" if task.pr_url else ":hedgehog:"


def gather_involved_tasks(
    *,
    slack_workspace_id: str,
    slack_user_id: str,
    accessible_integrations: list[Integration],
) -> list[HomeTabTask]:
    """Tasks the Slack user is involved in, across the teams they can access.

    Scoped to ``accessible_integrations`` (the teams the resolved PostHog user has
    access to in this workspace) so a Slack user never sees tasks from a team they
    can't access. Reads task display fields through the tasks facade — never the
    tasks ORM directly.
    """
    accessible_team_ids = {i.team_id for i in accessible_integrations}
    if not accessible_team_ids:
        return []

    mappings = (
        SlackThreadTaskMapping.objects.filter(
            slack_workspace_id=slack_workspace_id,
            team_id__in=accessible_team_ids,
            participant_slack_user_ids__contains=[slack_user_id],
        )
        .order_by("-updated_at")
        .values("task_id", "team_id", "updated_at")
    )

    # Dedupe by task, keeping the most recent mapping (the queryset is already
    # newest-first, so the first occurrence wins).
    task_to_team: dict[str, int] = {}
    task_sort: dict[str, datetime] = {}
    for row in mappings:
        task_id = str(row["task_id"])
        if task_id in task_to_team:
            continue
        task_to_team[task_id] = row["team_id"]
        task_sort[task_id] = row["updated_at"]
        if len(task_to_team) >= _MAX_TASKS:
            break

    if not task_to_team:
        return []

    # Fetch display fields per team via the tasks facade.
    task_ids_by_team: dict[int, list[str]] = {}
    for task_id, team_id in task_to_team.items():
        task_ids_by_team.setdefault(team_id, []).append(task_id)

    # Lazy import: the tasks facade pulls heavy logic/sandbox modules, and this
    # module is reachable from api.py on the django.setup() path. See task_creation.py.
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415

    tasks: list[HomeTabTask] = []
    for team_id, task_ids in task_ids_by_team.items():
        for card in tasks_facade.get_tasks_for_slack_home(team_id, task_ids):
            tasks.append(
                HomeTabTask(
                    task_id=str(card.task_id),
                    team_id=team_id,
                    title=card.title or "Untitled task",
                    repository=card.repository,
                    status=card.status or "NOT_STARTED",
                    stage=card.stage,
                    pr_url=card.pr_url,
                    error_message=card.error_message,
                    sort_key=task_sort[str(card.task_id)],
                )
            )

    tasks.sort(key=lambda t: t.sort_key, reverse=True)
    return tasks


def _task_block(task: HomeTabTask) -> dict:
    repo = f"  ·  `{task.repository}`" if task.repository else ""
    if task.is_active and task.stage:
        detail = f"\n_{task.stage}_"
    elif task.status.upper() == "FAILED" and task.error_message:
        # Keep it short — the full error lives on the task page.
        detail = f"\n_{task.error_message[:140]}_"
    else:
        detail = ""
    text = f"{_status_emoji(task)}  *{task.title}*{repo}{detail}"

    if task.pr_url:
        button = {"text": {"type": "plain_text", "text": "View PR"}, "url": task.pr_url, "action_id": "view_pr"}
    else:
        button = {
            "text": {"type": "plain_text", "text": "Open in PostHog"},
            "url": task.task_url,
            "action_id": "open_task",
        }
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
        "accessory": {"type": "button", **button},
    }


def build_home_view(tasks: list[HomeTabTask]) -> dict:
    """Build the Block Kit ``view`` payload for ``views.publish``."""
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "🦔 PostHog Code", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Tasks you started or replied to. Updates here silently — no pings.",
                }
            ],
        },
    ]

    if not tasks:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "No tasks yet. Mention *@PostHog* in a thread to start one.",
                },
            }
        )
        return {"type": "home", "blocks": blocks}

    active = [t for t in tasks if t.is_active]
    finished = [t for t in tasks if not t.is_active]

    if active:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*In progress ({len(active)})*"}})
        blocks.extend(_task_block(t) for t in active)

    if finished:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Recently finished ({len(finished)})*"}})
        blocks.extend(_task_block(t) for t in finished)

    return {"type": "home", "blocks": blocks}


def publish_home_tab(
    slack: SlackIntegration,
    *,
    slack_user_id: str,
    slack_workspace_id: str,
    accessible_integrations: list[Integration],
) -> None:
    """Render and publish the Home tab for one Slack user. Best-effort: logs and
    swallows Slack API errors so a failed publish never breaks event handling."""
    try:
        tasks = gather_involved_tasks(
            slack_workspace_id=slack_workspace_id,
            slack_user_id=slack_user_id,
            accessible_integrations=accessible_integrations,
        )
        view = build_home_view(tasks)
        slack.client.views_publish(user_id=slack_user_id, view=view)
    except Exception:
        logger.warning("slack_app_home_tab_publish_failed", exc_info=True)
