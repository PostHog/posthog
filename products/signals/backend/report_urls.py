"""Links to an inbox report that PostHog writes into other surfaces.

Each link carries a `source` query param. The inbox reads it, records it as `link_source` on
`Inbox report opened`, and removes it from the address bar. The values must match
`INBOX_REPORT_LINK_SOURCES` in `frontend/inbox/inboxAnalytics.ts`.
"""

from enum import StrEnum
from uuid import UUID

from posthog.utils import absolute_uri


class ReportLinkSource(StrEnum):
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


def report_path(team_id: int, report_id: str | UUID, source: ReportLinkSource) -> str:
    return f"/project/{team_id}/inbox/reports/{report_id}?source={source.value}"


def build_report_url(team_id: int, report_id: str | UUID, source: ReportLinkSource) -> str:
    return absolute_uri(report_path(team_id, report_id, source))
