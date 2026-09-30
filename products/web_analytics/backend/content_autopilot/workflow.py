from django.db import transaction

from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot import lifecycle, opportunities
from products.web_analytics.backend.models import ContentAutopilotProposal, ContentAutopilotRun
from products.web_analytics.backend.tasks.content_autopilot import (
    generate_content_autopilot_run_task,
    process_content_autopilot_proposal_task,
)


def draft_opportunities(
    *, team: Team, profile_id: str, opportunity_ids: list[str], triggered_by_id: int | None
) -> ContentAutopilotRun:
    run = opportunities.draft_opportunities(
        team=team, profile_id=profile_id, opportunity_ids=opportunity_ids, triggered_by_id=triggered_by_id
    )
    team_id, run_id = run.team_id, str(run.id)
    transaction.on_commit(lambda: generate_content_autopilot_run_task.delay(team_id, run_id))
    return run


def edit_proposal(
    *, team: Team, proposal_id: str, proposed_markdown: str, content_package: dict[str, object]
) -> ContentAutopilotProposal:
    proposal = lifecycle.edit_proposal(
        team=team, proposal_id=proposal_id, proposed_markdown=proposed_markdown, content_package=content_package
    )
    team_id = proposal.team_id
    transaction.on_commit(lambda: process_content_autopilot_proposal_task.delay(team_id, proposal_id, "validate"))
    return proposal


def regenerate_proposal(*, team: Team, proposal_id: str) -> ContentAutopilotProposal:
    proposal = lifecycle.regenerate_proposal(team=team, proposal_id=proposal_id)
    team_id = proposal.team_id
    transaction.on_commit(lambda: process_content_autopilot_proposal_task.delay(team_id, proposal_id, "regenerate"))
    return proposal
