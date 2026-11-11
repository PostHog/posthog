from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot import lifecycle, opportunities
from products.web_analytics.backend.content_autopilot.generation import ProposalMode, fail_proposal, finish_run
from products.web_analytics.backend.models import ContentAutopilotProposal, ContentAutopilotRun
from products.web_analytics.backend.tasks.content_autopilot import (
    generate_content_autopilot_run_task,
    process_content_autopilot_proposal_task,
)

logger = structlog.get_logger(__name__)


def _start_run(team_id: int, run_id: str) -> None:
    try:
        generate_content_autopilot_run_task.delay(team_id, run_id)
    except Exception as error:
        capture_exception(error)
        logger.exception("content_autopilot_run_dispatch_failed", team_id=team_id, run_id=run_id)
        error_entry = {
            "error_code": "dispatch_failed",
            "message": "Drafting couldn't start. Select opportunities and draft them again.",
        }
        finish_run(team_id, run_id, errors=[error_entry], ready=0)


def _start_proposal(team_id: int, proposal_id: str, mode: ProposalMode) -> None:
    try:
        process_content_autopilot_proposal_task.delay(team_id, proposal_id, mode)
    except Exception as error:
        capture_exception(error)
        logger.exception("content_autopilot_proposal_dispatch_failed", team_id=team_id, proposal_id=proposal_id)
        fail_proposal(team_id, proposal_id, "Drafting couldn't start. Regenerate to try again.")


def draft_opportunities(
    *, team: Team, profile_id: str, opportunity_ids: list[str], triggered_by_id: int | None
) -> ContentAutopilotRun:
    run = opportunities.draft_opportunities(
        team=team, profile_id=profile_id, opportunity_ids=opportunity_ids, triggered_by_id=triggered_by_id
    )
    team_id, run_id = run.team_id, str(run.id)
    transaction.on_commit(lambda: _start_run(team_id, run_id))
    return run


def edit_proposal(
    *, team: Team, proposal_id: str, proposed_markdown: str, content_package: dict[str, object]
) -> ContentAutopilotProposal:
    proposal = lifecycle.edit_proposal(
        team=team, proposal_id=proposal_id, proposed_markdown=proposed_markdown, content_package=content_package
    )
    team_id = proposal.team_id
    transaction.on_commit(lambda: _start_proposal(team_id, proposal_id, "validate"))
    return proposal


def regenerate_proposal(*, team: Team, proposal_id: str) -> ContentAutopilotProposal:
    proposal = lifecycle.regenerate_proposal(team=team, proposal_id=proposal_id)
    team_id = proposal.team_id
    transaction.on_commit(lambda: _start_proposal(team_id, proposal_id, "regenerate"))
    return proposal
