"""Links to an inbox report that PostHog writes into other surfaces.

Each link carries a `link_source` query param. The inbox reads it, records it on
`Inbox report opened`, and removes it from the address bar. The inbox filters already use `source`. The values must match
`INBOX_REPORT_LINK_SOURCES` in `frontend/inbox/inboxAnalytics.ts`.

A link can also carry a `link_action` query param. The inbox reads it once and removes it too.
"""

import re
from enum import StrEnum
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.utils import absolute_uri

# Both live path shapes: `/inbox/<report_id>`, which the MCP tools return and the web app redirects, and the web
# app's own `/inbox/<tab>/<report_id>`. The trailing guards reject a longer id and a deeper path, so a query string
# or a fragment can follow but `/inbox/scouts/<skill>/<finding_id>` does not match.
_REPORT_PATH_PATTERN = re.compile(
    r"/project/(?P<team_id>\d{1,18})/inbox/(?:[a-z][a-z-]*/)?"
    r"(?P<report_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"(?![\w-])(?!/\w)",
    re.IGNORECASE,
)


class ReportLinkSource(StrEnum):
    FIRST_REPORT_EMAIL = "first_report_email"
    MCP = "mcp"
    SLACK = "slack"
    SLACK_SCOUT = "slack_scout"
    SCOUT = "scout"
    GITHUB_COMMENT = "github_comment"
    GITHUB_PR = "github_pr"
    TRACKER = "tracker"
    SUPPORT = "support"
    TASK = "task"
    TODAY = "today"
    NOTE_MENTION = "note_mention"


class ReportLinkAction(StrEnum):
    # Opens the implementation choices of the report's Implement button.
    IMPLEMENT = "implement"


def _bare_report_path(team_id: int, report_id: str | UUID) -> str:
    return f"/project/{team_id}/inbox/reports/{report_id}"


def report_path(
    team_id: int, report_id: str | UUID, source: ReportLinkSource, action: ReportLinkAction | None = None
) -> str:
    path = f"{_bare_report_path(team_id, report_id)}?link_source={source.value}"
    return f"{path}&link_action={action.value}" if action else path


def build_report_url(
    team_id: int, report_id: str | UUID, source: ReportLinkSource, action: ReportLinkAction | None = None
) -> str:
    return absolute_uri(report_path(team_id, report_id, source, action))


def build_bare_report_url(team_id: int, report_id: str | UUID) -> str:
    """The report's URL without a `link_source`, for payloads that leave PostHog to a system we do not know."""
    return absolute_uri(_bare_report_path(team_id, report_id))


@frozen
class ReportReference:
    team_id: int
    report_id: UUID


def report_references(text: str) -> list[ReportReference]:
    """The reports that report URLs in `text` point at, in order of first appearance and without repeats.

    Only the path is read, so the host does not matter. Nothing here checks that the team or the report exists.
    """
    references: dict[ReportReference, None] = {}
    for match in _REPORT_PATH_PATTERN.finditer(text):
        references.setdefault(ReportReference(team_id=int(match["team_id"]), report_id=UUID(match["report_id"])), None)
    return list(references)
