from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot import opportunities, workflow
from products.web_analytics.backend.content_autopilot.export import ContentAutopilotExportError, export_proposal
from products.web_analytics.backend.content_autopilot.lifecycle import (
    MAX_PROPOSAL_MARKDOWN_CHARS,
    ContentAutopilotLifecycleError,
    cancel_run,
    delete_profile,
    reject_proposal,
    start_run,
)
from products.web_analytics.backend.content_autopilot.opportunities import (
    MAX_DRAFTS_PER_RUN,
    MAX_REFRESHED_OPPORTUNITIES,
)
from products.web_analytics.backend.content_autopilot.site_discovery import (
    discover_site,
    has_same_public_origin,
    normalize_site_origin,
)
from products.web_analytics.backend.content_autopilot.workflow import edit_proposal, regenerate_proposal
from products.web_analytics.backend.public_url_fetch import PublicUrlFetchError

__all__ = [
    "MAX_DRAFTS_PER_RUN",
    "MAX_PROPOSAL_MARKDOWN_CHARS",
    "MAX_REFRESHED_OPPORTUNITIES",
    "ContentAutopilotExportError",
    "ContentAutopilotLifecycleError",
    "PublicUrlFetchError",
    "cancel_run",
    "delete_profile",
    "discover_site",
    "dismiss_opportunity",
    "draft_opportunities",
    "edit_proposal",
    "export_proposal",
    "has_same_public_origin",
    "normalize_site_origin",
    "refresh_opportunities",
    "regenerate_proposal",
    "reject_proposal",
    "start_run",
]


def refresh_opportunities(*, team: Team, profile_id: str) -> None:
    opportunities.refresh_opportunities(team=team, profile_id=profile_id)


def dismiss_opportunity(*, team: Team, opportunity_id: str) -> None:
    opportunities.dismiss_opportunity(team=team, opportunity_id=opportunity_id)


def draft_opportunities(*, team: Team, profile_id: str, opportunity_ids: list[str], triggered_by_id: int | None) -> str:
    run = workflow.draft_opportunities(
        team=team, profile_id=profile_id, opportunity_ids=opportunity_ids, triggered_by_id=triggered_by_id
    )
    return str(run.id)
