"""Slack App Home tab for the PostHog coding agent.

The Home tab is a per-user surface we can refresh silently with ``views.publish``
(no thread reply, no mention, no Activity-feed entry). It shows the tasks a Slack
user is involved in — ones they started by @-mentioning the bot, or ones they
replied into ("multiplayer"). Involvement is recorded on
``SlackThreadTaskMapping.participant_slack_user_ids``.

This module owns: gathering the involved tasks (from slack_app's own mapping
table, joined to the tasks product *only* through its facade), filtering them, and
rendering + publishing the Block Kit view.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from posthog.models.integration import Integration, SlackIntegration
from posthog.utils import absolute_uri

from products.slack_app.backend.models import SlackThreadTaskMapping

logger = logging.getLogger(__name__)

# Action ids for the in-tab controls. Handled by the interactivity callback, which
# re-publishes the view (preserving the current filter selection). Defined here so
# api.py and the view builder agree.
REFRESH_HOME_ACTION_ID = "refresh_home"
FILTER_ORG_ACTION_ID = "home_filter_org"
FILTER_REPO_ACTION_ID = "home_filter_repo"
FILTER_STATUS_ACTION_ID = "home_filter_status"
HOME_ACTION_IDS = frozenset(
    {REFRESH_HOME_ACTION_ID, FILTER_ORG_ACTION_ID, FILTER_REPO_ACTION_ID, FILTER_STATUS_ACTION_ID}
)

# Sentinel for a filter's "no filter" option.
_ALL = "__all__"

# How many recent involved tasks to render. The Home tab is a glanceable summary,
# not a full task list — the title links lead to the complete history in PostHog.
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
    # True when the viewer only replied in the thread — someone else started the
    # task. Drives the "joined" marker so owned vs. multiplayer tasks read differently.
    joined: bool = False
    org_id: str = ""
    org_name: str = ""

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

    # team_id -> (org_id, org_name) for the org filter / labels.
    team_org: dict[int, tuple[str, str]] = {}
    for i in accessible_integrations:
        team = getattr(i, "team", None)
        if team is None:
            continue
        org = getattr(team, "organization", None)
        team_org[i.team_id] = (str(getattr(team, "organization_id", "") or ""), getattr(org, "name", "") if org else "")

    mappings = (
        SlackThreadTaskMapping.objects.filter(
            slack_workspace_id=slack_workspace_id,
            team_id__in=accessible_team_ids,
            participant_slack_user_ids__contains=[slack_user_id],
        )
        .order_by("-updated_at")
        .values("task_id", "team_id", "updated_at", "mentioning_slack_user_id")
    )

    # Dedupe by task, keeping the most recent mapping (the queryset is already
    # newest-first, so the first occurrence wins).
    task_to_team: dict[str, int] = {}
    task_sort: dict[str, datetime] = {}
    task_joined: dict[str, bool] = {}
    for row in mappings:
        task_id = str(row["task_id"])
        if task_id in task_to_team:
            continue
        task_to_team[task_id] = row["team_id"]
        task_sort[task_id] = row["updated_at"]
        # "joined" = the viewer didn't start the thread, they replied into it.
        task_joined[task_id] = row["mentioning_slack_user_id"] != slack_user_id
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
        org_id, org_name = team_org.get(team_id, ("", ""))
        for card in tasks_facade.get_tasks_for_slack_home(team_id, task_ids):
            tid = str(card.task_id)
            tasks.append(
                HomeTabTask(
                    task_id=tid,
                    team_id=team_id,
                    title=card.title or "Untitled task",
                    repository=card.repository,
                    status=card.status or "NOT_STARTED",
                    stage=card.stage,
                    pr_url=card.pr_url,
                    error_message=card.error_message,
                    sort_key=task_sort[tid],
                    joined=task_joined.get(tid, False),
                    org_id=org_id,
                    org_name=org_name,
                )
            )

    tasks.sort(key=lambda t: t.sort_key, reverse=True)
    return tasks


def apply_filters(tasks: list[HomeTabTask], filters: dict[str, str]) -> list[HomeTabTask]:
    """Filter tasks by the selected org / repo / status (each defaults to all)."""
    org = filters.get("org") or _ALL
    repo = filters.get("repo") or _ALL
    status = filters.get("status") or _ALL

    out = tasks
    if org != _ALL:
        out = [t for t in out if t.org_id == org]
    if repo != _ALL:
        out = [t for t in out if t.repository == repo]
    if status == "active":
        out = [t for t in out if t.is_active]
    elif status == "finished":
        out = [t for t in out if not t.is_active]
    return out


def _humanize_status(status: str) -> str:
    return (status or "").replace("_", " ").lower() or "unknown"


def _detail_text(task: HomeTabTask) -> str:
    """The muted status fragment shown after the repo in a task's context line."""
    if task.is_active:
        return task.stage.strip() if task.stage else _humanize_status(task.status)
    status = (task.status or "").upper()
    if status == "COMPLETED":
        if task.pr_url:
            return f"<{task.pr_url}|View PR ↗>"
        return "done"
    if status == "FAILED":
        return f"failed — {task.error_message[:120]}" if task.error_message else "failed"
    if status == "CANCELLED":
        return "cancelled"
    return _humanize_status(task.status)


def _task_blocks(task: HomeTabTask) -> list[dict]:
    """A task row: a section with the clickable title + a muted context line."""
    title = f"{_status_emoji(task)}  *<{task.task_url}|{task.title}>*"

    context_parts: list[str] = []
    if task.repository:
        context_parts.append(f"`{task.repository}`")
    context_parts.append(_detail_text(task))
    if task.joined:
        context_parts.append(":bust_in_silhouette: joined")

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "  ·  ".join(context_parts)}]},
    ]


def _option(label: str, value: str) -> dict:
    # Slack caps option/placeholder text at 75 chars.
    return {"text": {"type": "plain_text", "text": label[:75]}, "value": value}


def _select(action_id: str, all_label: str, options: list[tuple[str, str]], selected: str) -> dict:
    opts = [_option(all_label, _ALL)] + [_option(label, value) for value, label in options]
    chosen = next((o for o in opts if o["value"] == (selected or _ALL)), opts[0])
    return {
        "type": "static_select",
        "action_id": action_id,
        "placeholder": {"type": "plain_text", "text": all_label[:75]},
        "options": opts,
        "initial_option": chosen,
    }


def _filter_block(tasks: list[HomeTabTask], filters: dict[str, str]) -> dict:
    """Org / repo / status selects + the Refresh button, in one actions row."""
    orgs = sorted({(t.org_id, t.org_name or "Organization") for t in tasks if t.org_id})
    repos = sorted({t.repository for t in tasks if t.repository})

    elements: list[dict] = []
    # Only show org / repo selects when there's more than one to choose from.
    if len({o[0] for o in orgs}) > 1:
        elements.append(_select(FILTER_ORG_ACTION_ID, "All orgs", orgs, filters.get("org", _ALL)))
    if len(repos) > 1:
        elements.append(_select(FILTER_REPO_ACTION_ID, "All repos", [(r, r) for r in repos], filters.get("repo", _ALL)))
    elements.append(
        _select(
            FILTER_STATUS_ACTION_ID,
            "All statuses",
            [("active", "In progress"), ("finished", "Recently finished")],
            filters.get("status", _ALL),
        )
    )
    elements.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "text": ":arrows_counterclockwise: Refresh", "emoji": True},
            "action_id": REFRESH_HOME_ACTION_ID,
        }
    )
    return {"type": "actions", "elements": elements}


def _summary_block(active: int, finished: int) -> dict:
    epoch = int(timezone.now().timestamp())
    counts = f"*{finished}* finished  ·  *{active}* in progress"
    # Slack renders <!date> in the viewer's own timezone.
    updated = f"<!date^{epoch}^updated {{time}}|updated just now>"
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{counts}  ·  {updated}"}]}


def _group(label: str, tasks: list[HomeTabTask]) -> list[dict]:
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{label}*"}}]
    for task in tasks:
        blocks.extend(_task_blocks(task))
    return blocks


def _intro_blocks() -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "🦔 PostHog Code", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "👋 Hello there! View your PostHog tasks here."}]},
    ]


def build_home_view(tasks: list[HomeTabTask], filters: dict[str, str] | None = None) -> dict:
    """Build the Block Kit ``view`` payload for ``views.publish``.

    ``tasks`` is the full involved-task set; ``filters`` (org / repo / status) selects
    the subset to display while the controls stay populated from the full set.
    """
    filters = filters or {}
    blocks: list[dict] = _intro_blocks()

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

    blocks.append(_filter_block(tasks, filters))

    shown = apply_filters(tasks, filters)
    active = [t for t in shown if t.is_active]
    finished = [t for t in shown if not t.is_active]
    blocks.append(_summary_block(len(active), len(finished)))

    if not shown:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No tasks match these filters._"}})
        return {"type": "home", "blocks": blocks}

    # Recently finished first — the Home tab is where you check what landed, not
    # what's still running.
    if finished:
        blocks.append({"type": "divider"})
        blocks.extend(_group("Recently finished", finished))
    if active:
        blocks.append({"type": "divider"})
        blocks.extend(_group("In progress", active))

    return {"type": "home", "blocks": blocks}


def publish_home_tab(
    slack: SlackIntegration,
    *,
    slack_user_id: str,
    slack_workspace_id: str,
    accessible_integrations: list[Integration],
    filters: dict[str, str] | None = None,
) -> None:
    """Render and publish the Home tab for one Slack user. Best-effort: logs and
    swallows Slack API errors so a failed publish never breaks event handling."""
    try:
        tasks = gather_involved_tasks(
            slack_workspace_id=slack_workspace_id,
            slack_user_id=slack_user_id,
            accessible_integrations=accessible_integrations,
        )
        view = build_home_view(tasks, filters)
        slack.client.views_publish(user_id=slack_user_id, view=view)
    except Exception:
        logger.warning("slack_app_home_tab_publish_failed", exc_info=True)
