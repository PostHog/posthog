from collections.abc import Sequence

from posthog.dataclasses import frozen

from products.tasks.backend.facade.domain_research import DomainResearch

TOP_OF_MIND = "Ask what's top of mind."

WELCOME_LINE = "Open with: Welcome to PostHog Desktop."

RESEARCH_LINE = "Say you did some research to start building their company context."

SAVE_CONTEXT = (
    "Save what the company does to this space's context, once they confirm your summary, correct it, "
    "or tell you from scratch."
)

NO_DATA_YET = (
    "Their project has nothing flowing into PostHog yet, so anything you might look at does not "
    "exist. Adding PostHog is the only real offer. This app ships a skill for it, so offer a "
    "composer prefilled with `/instrument-product-analytics`. Do not manufacture another offer."
)

HAS_DATA = "Their project has data flowing, so whatever they name is something you can act on now."

_NAMED_SOURCE_LIMIT = 3


@frozen
class OnboardingFacts:
    org_has_context: bool
    research: DomainResearch | None = None
    has_events: bool = False
    signal_reports_waiting: int = 0
    sources_enabled: tuple[str, ...] = ()
    sources_newly_enabled: bool = False
    other_members: str | None = None


def prose_list(items: Sequence[str], *, limit: int = 3) -> str | None:
    """``a``, ``a and b``, ``a, b and c``, then ``a, b and 4 others``.

    ``limit`` counts the whole phrase, so a list that overflows spends its last slot on the count
    rather than on one more name.
    """
    if not items:
        return None
    if len(items) <= limit:
        named = list(items)
    else:
        named = [*items[: limit - 1], f"{len(items) - limit + 1} others"]
    if len(named) == 1:
        return named[0]
    return f"{', '.join(named[:-1])} and {named[-1]}"


def _joining_brief(facts: OnboardingFacts) -> list[str]:
    welcome = "Welcome them to the workspace."
    if facts.other_members:
        welcome += f" Say that {facts.other_members} are already here."
    brief = [welcome]
    status = _status_line(facts)
    if status:
        brief.append(status)
    if facts.signal_reports_waiting:
        brief.append("Offer to walk them through one of the findings.")
    brief.append(TOP_OF_MIND)
    return brief


def _findings_line(facts: OnboardingFacts) -> str:
    return f"Say that {facts.signal_reports_waiting} findings are waiting in #general."


def _status_line(facts: OnboardingFacts) -> str | None:
    if facts.signal_reports_waiting:
        return _findings_line(facts)
    if not facts.has_events:
        return "Say plainly that no PostHog data is arriving yet, because nothing is connected to send it."
    enabled = prose_list(facts.sources_enabled, limit=_NAMED_SOURCE_LIMIT)
    if not enabled:
        return None
    if facts.sources_newly_enabled:
        return f"Tell them you turned on {enabled}, so findings will start landing in #general."
    return f"Tell them you are watching {enabled}, and findings will land in #general as they come up."


def _offer_line(facts: OnboardingFacts) -> str | None:
    if not facts.has_events:
        return (
            "Offer to add PostHog to their codebase and open a pull request for them to review, "
            "and ask which repository to add it to. Make it something they accept, not something "
            "you have started."
        )
    if facts.signal_reports_waiting:
        return "Offer to walk them through one of the findings that is waiting."
    return None


def build_opening_brief(facts: OnboardingFacts) -> list[str]:
    if facts.org_has_context:
        return _joining_brief(facts)

    scraped = facts.research is not None and facts.research.outcome == "scraped"
    brief = [WELCOME_LINE]
    asked_top_of_mind = False

    if scraped and facts.research is not None:
        brief.append(RESEARCH_LINE)
        brief.append("Summarize what the company does, from the page below, and ask whether that is right.")
    elif facts.research is not None and facts.research.outcome == "unreachable":
        brief.append(
            f"Say you tried to read {facts.research.url} to start building their company context, "
            "but could not reach it. Then ask what the company does."
        )
    else:
        asked_top_of_mind = True
        brief.append(
            "Ask one real question so you can be useful rather than generic: what are they working on right now?"
        )

    status = _status_line(facts)
    if status:
        brief.append(status)

    offer = _offer_line(facts)
    if offer:
        brief.append(offer)
    if not asked_top_of_mind:
        brief.append(TOP_OF_MIND)

    if scraped and facts.research is not None:
        brief.append(f"Last line, exactly: Sources: {facts.research.url}")

    return brief


def build_followup(facts: OnboardingFacts) -> list[str]:
    followup = [] if facts.org_has_context else [SAVE_CONTEXT]
    followup.append(HAS_DATA if facts.has_events else NO_DATA_YET)
    return followup
