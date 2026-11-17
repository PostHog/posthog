"""The reviewer's verdict, derived in code from the facts the LLM reports.

The LLM answers the policy's questions (which risky territory the diff enters, which
assurance covers it, which concerns and refusal grounds stand) and this module applies
the policy's decision rule to those answers. A model asked for a verdict directly sees
the same facts but does not apply the rule to them reliably, so the rule is not left to it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["APPROVE", "REFUSE", "ESCALATE"]
Risk = Literal["low", "medium", "high"]

_FACT_LIST_FIELDS = (
    "risky_areas",
    "reviews_on_current_head",
    "unresolved_substantive_concerns",
    "other_refusal_grounds",
)
_FACT_BOOL_FIELDS = ("owning_team_author", "strong_familiarity")
FACT_FIELDS = (*_FACT_LIST_FIELDS, *_FACT_BOOL_FIELDS)

_STRING_LIST = {"type": "array", "items": {"type": "string"}}

FACTS_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "risky_areas": _STRING_LIST,
            "reviews_on_current_head": _STRING_LIST,
            "owning_team_author": {"type": "boolean"},
            "strong_familiarity": {"type": "boolean"},
            "unresolved_substantive_concerns": _STRING_LIST,
            "other_refusal_grounds": _STRING_LIST,
            "reasoning": {"type": "string"},
            # The digest splits the per-team clauses back out of this text on the handles they
            # open with (_TEAM_CLAUSE_RE in products/stamphog/backend/logic/digest.py). A clause
            # that regex does not recognize takes its team's merge out of that team's digest, so
            # the clause shape the reviewer prompt asks for is a contract with that parser.
            "change_summary": {"type": "string", "maxLength": 600},
        },
        "required": [*FACT_FIELDS, "reasoning", "change_summary"],
        "additionalProperties": False,
    },
}


class InvalidFactsError(ValueError):
    pass


@dataclass(frozen=True, kw_only=True)
class ReviewFacts:
    risky_areas: tuple[str, ...]
    reviews_on_current_head: tuple[str, ...]
    owning_team_author: bool
    strong_familiarity: bool
    unresolved_substantive_concerns: tuple[str, ...]
    other_refusal_grounds: tuple[str, ...]

    @classmethod
    def from_output(cls, output: Mapping[str, object]) -> "ReviewFacts":
        """Read the facts from the reviewer's structured output, or raise InvalidFactsError."""
        lists: dict[str, tuple[str, ...]] = {}
        for name in _FACT_LIST_FIELDS:
            value = output.get(name)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise InvalidFactsError(f"{name} is not a list of strings")
            # A blank entry carries no evidence, and counting it would refuse or escalate on nothing.
            lists[name] = tuple(item.strip() for item in value if item.strip())
        flags: dict[str, bool] = {}
        for name in _FACT_BOOL_FIELDS:
            value = output.get(name)
            if not isinstance(value, bool):
                raise InvalidFactsError(f"{name} is not a boolean")
            flags[name] = value
        return cls(
            risky_areas=lists["risky_areas"],
            reviews_on_current_head=lists["reviews_on_current_head"],
            owning_team_author=flags["owning_team_author"],
            strong_familiarity=flags["strong_familiarity"],
            unresolved_substantive_concerns=lists["unresolved_substantive_concerns"],
            other_refusal_grounds=lists["other_refusal_grounds"],
        )


@dataclass(frozen=True, kw_only=True)
class RuledVerdict:
    verdict: Verdict
    risk: Risk
    issues: tuple[str, ...]


def derive_verdict(facts: ReviewFacts) -> RuledVerdict:
    """Apply the review guidance's decision rule to the reported facts.

    Refusal grounds and unresolved concerns refuse anywhere. Risky territory needs
    independent assurance: a current-head review, or an author on the owning team or
    with STRONG familiarity. Without any of them the PR escalates to a human.
    """
    issues = [*facts.unresolved_substantive_concerns, *facts.other_refusal_grounds]
    assured = bool(facts.reviews_on_current_head) or facts.owning_team_author or facts.strong_familiarity

    verdict: Verdict
    if issues:
        verdict = "REFUSE"
    elif facts.risky_areas and not assured:
        verdict = "ESCALATE"
        issues.append("Risky territory without independent assurance: " + "; ".join(facts.risky_areas))
    else:
        verdict = "APPROVE"

    risk: Risk
    if facts.risky_areas and verdict != "APPROVE":
        risk = "high"
    elif facts.risky_areas:
        risk = "medium"
    else:
        risk = "low"
    return RuledVerdict(verdict=verdict, risk=risk, issues=tuple(issues))


def facts_summary(facts: object) -> dict[str, int | bool] | None:
    """Counts and flags of the reported facts for analytics, or None when they do not parse."""
    if not isinstance(facts, Mapping):
        return None
    try:
        parsed = ReviewFacts.from_output(facts)
    except InvalidFactsError:
        return None
    return {
        "risky_areas": len(parsed.risky_areas),
        "reviews_on_current_head": len(parsed.reviews_on_current_head),
        "owning_team_author": parsed.owning_team_author,
        "strong_familiarity": parsed.strong_familiarity,
        "unresolved_substantive_concerns": len(parsed.unresolved_substantive_concerns),
        "other_refusal_grounds": len(parsed.other_refusal_grounds),
    }
