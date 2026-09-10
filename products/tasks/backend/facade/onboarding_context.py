"""Write what setup learned about the company into the space's context."""

import re

import structlog

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.facade.api import (
    ChannelInstructionsTooLargeError,
    ChannelInstructionsVersionConflictError,
    ChannelInstructionsVersionLimitError,
    find_general_channel_id,
    get_channel_instructions,
    publish_channel_instructions,
)
from products.tasks.backend.facade.domain_research import normalize_target

logger = structlog.get_logger(__name__)

COMPANY_HEADING = "## Company"

_SECTION_BREAK = re.compile(r"^## ", re.MULTILINE)


@frozen
class CompanyAnswer:
    """What the company step of setup collected. Every field is the person's own answer, so
    nothing here is asked again in the session that follows."""

    url: str | None = None
    description: str = ""
    building: str = ""

    @property
    def is_blank(self) -> bool:
        return not (self.url or self.description.strip() or self.building.strip())


def _demoted(text: str) -> str:
    """A line of theirs that opens a markdown heading would end the section early."""
    return "\n".join(line.lstrip("#").lstrip() if line.startswith("#") else line for line in text.strip().splitlines())


def company_section(company: CompanyAnswer) -> str:
    body = [COMPANY_HEADING, ""]
    if company.description.strip():
        body.append(_demoted(company.description))
        body.append("")
    if company.url:
        body.append(f"Website: {company.url}")
        body.append("")
    if company.building.strip():
        body.append(f"What they are building: {_demoted(company.building)}")
        body.append("")
    body.append(
        "They gave this in setup, in their own words. Ask about it only when what you are doing needs more than it says."
    )
    return "\n".join(body)


def with_company_section(existing: str, company: CompanyAnswer) -> str:
    """The context with the company section replaced, or appended when it isn't there yet."""
    section = company_section(company)
    heading_at = existing.find(COMPANY_HEADING)
    if heading_at == -1:
        return f"{existing.rstrip()}\n\n{section}\n" if existing.strip() else f"{section}\n"
    next_section = _SECTION_BREAK.search(existing, heading_at + len(COMPANY_HEADING))
    tail = existing[next_section.start() :] if next_section else ""
    return f"{existing[:heading_at]}{section}\n\n{tail}".rstrip() + "\n"


def record_company_answer(team: Team, user: User, company: CompanyAnswer) -> bool:
    """Best-effort: a session that opens without the context beats no session."""
    if company.is_blank:
        return False
    channel_id = find_general_channel_id(team.id)
    if channel_id is None:
        return False
    try:
        current = get_channel_instructions(channel_id, team.id, user.id)
        if current is None:
            return False
        publish_channel_instructions(
            channel_id,
            team.id,
            user.id,
            content=with_company_section(current.content, company),
            base_version=current.version,
        )
    except (
        ChannelInstructionsTooLargeError,
        ChannelInstructionsVersionConflictError,
        ChannelInstructionsVersionLimitError,
    ):
        logger.warning("onboarding_company_context_not_written", team_id=team.id, exc_info=True)
        return False
    return True


def company_answer_from(url: str, description: str, building: str) -> CompanyAnswer:
    return CompanyAnswer(
        url=normalize_target(url) if url.strip() else None,
        description=description.strip(),
        building=building.strip(),
    )
