from collections.abc import Sequence

from posthog.dataclasses import frozen

from products.tasks.backend.facade.domain_research import DomainResearch

TOP_OF_MIND = "Ask what's top of mind."

RESEARCH_LINE = "Say you did some research to start building their company context."

SAVE_CONTEXT = (
    "Save what the company does to this space's context, once they confirm your summary, correct it, "
    "or tell you from scratch."
)

NO_FOLLOWUP = "Nothing beyond answering them."

# How many turned-on sources the message names before it starts counting. Naming all of them reads
# as a feature list and eats the word budget the company summary needs.
_NAMED_SOURCE_LIMIT = 3


@frozen
class OnboardingFacts:
    org_has_context: bool
    research: DomainResearch | None = None
    has_events: bool = False
    signal_reports_waiting: int = 0
    sources_enabled: tuple[str, ...] = ()
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
    return [
        welcome,
        _findings_line(facts),
        "Offer to walk them through one of the findings.",
        TOP_OF_MIND,
    ]


def _findings_line(facts: OnboardingFacts) -> str:
    return f"Say that {facts.signal_reports_waiting} findings are waiting in #general."


def _status_line(facts: OnboardingFacts) -> str | None:
    if facts.signal_reports_waiting:
        return _findings_line(facts)
    if not facts.has_events:
        return "Say plainly that no PostHog data is arriving yet, because nothing is connected to send it."
    enabled = prose_list(facts.sources_enabled, limit=_NAMED_SOURCE_LIMIT)
    if enabled:
        return f"Tell them you turned on {enabled}, so findings will start landing in #general."
    return None


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
    brief = [RESEARCH_LINE]

    if scraped:
        brief.append("Summarize what the company does, from the page below, and ask whether that is right.")
    else:
        brief.append("Say you could not read their site, and ask what the company does.")

    status = _status_line(facts)
    if status:
        brief.append(status)

    offer = _offer_line(facts)
    if offer:
        brief.append(offer)
    brief.append(TOP_OF_MIND)

    if scraped and facts.research is not None:
        brief.append(f"Last line, exactly: Sources: {facts.research.url}")

    return brief


def build_followup(facts: OnboardingFacts) -> str:
    """What the session owes them after the first message. Kept out of the brief so a line meant for
    the agent can never be transcribed into the message as a point to cover."""
    return NO_FOLLOWUP if facts.org_has_context else SAVE_CONTEXT
