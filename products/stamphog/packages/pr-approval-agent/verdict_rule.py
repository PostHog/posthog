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
FACT_FIELDS = (*_FACT_LIST_FIELDS, *_FACT_BOOL_FIELDS, "rejected_bot_concerns")

_STRING_LIST = {"type": "array", "items": {"type": "string"}}

# A wrong call on these costs too much to settle on an automated judge's reading, so the author's
# rejection never resolves them: they need a code fix or a person's sign-off in the thread.
STRICT_CONCERN_CATEGORIES = ("security", "auth", "data_loss", "migration")
CONCERN_CATEGORIES = (*STRICT_CONCERN_CATEGORIES, "other")

_REJECTED_CONCERN_FIELDS = ("bot", "concern", "category", "rejection_holds", "evidence")
_REJECTED_CONCERN = {
    "type": "object",
    "properties": {
        "bot": {"type": "string"},
        "concern": {"type": "string"},
        "category": {"type": "string", "enum": list(CONCERN_CATEGORIES)},
        "rejection_holds": {"type": "boolean"},
        "evidence": {"type": "string"},
    },
    "required": list(_REJECTED_CONCERN_FIELDS),
    "additionalProperties": False,
}

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
            "rejected_bot_concerns": {"type": "array", "items": _REJECTED_CONCERN},
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


def bot_handle(login: str) -> str:
    """A login in one spelling: GraphQL drops the `[bot]` suffix that REST and the model may write."""
    handle = login.strip().lstrip("@").lower()
    return handle.removesuffix("[bot]")


@dataclass(frozen=True, kw_only=True)
class RejectedConcern:
    """A reviewer bot's finding that the PR author rejected in its thread, as the reviewer judged it."""

    bot: str
    concern: str
    category: str
    rejection_holds: bool
    evidence: str

    @classmethod
    def from_output(cls, item: object) -> "RejectedConcern":
        if not isinstance(item, Mapping) or set(item) != set(_REJECTED_CONCERN_FIELDS):
            raise InvalidFactsError("rejected_bot_concerns entry has the wrong fields")
        strings = {name: item[name] for name in ("bot", "concern", "category", "evidence")}
        if not all(isinstance(value, str) for value in strings.values()):
            raise InvalidFactsError("rejected_bot_concerns entry has a non-string field")
        if item["category"] not in CONCERN_CATEGORIES:
            raise InvalidFactsError(f"rejected_bot_concerns category {item['category']!r} is unknown")
        if not isinstance(item["rejection_holds"], bool):
            raise InvalidFactsError("rejected_bot_concerns rejection_holds is not a boolean")
        return cls(
            bot=item["bot"].strip(),
            concern=item["concern"].strip(),
            category=item["category"],
            rejection_holds=item["rejection_holds"],
            evidence=item["evidence"].strip(),
        )

    def why_open(self, reviewing_bots: frozenset[str]) -> str | None:
        """Why this finding still blocks, or None when the author's rejection resolves it."""
        if bot_handle(self.bot) not in reviewing_bots:
            return "it was not raised by a reviewer bot, so the person who raised it has to accept the answer"
        if self.category in STRICT_CONCERN_CATEGORIES:
            return f"a {self.category.replace('_', ' ')} finding needs a code fix or a person's sign-off"
        if not self.rejection_holds:
            return f"the author's rejection does not hold: {self.evidence}"
        return None


@dataclass(frozen=True, kw_only=True)
class ReviewFacts:
    risky_areas: tuple[str, ...]
    reviews_on_current_head: tuple[str, ...]
    owning_team_author: bool
    strong_familiarity: bool
    unresolved_substantive_concerns: tuple[str, ...]
    other_refusal_grounds: tuple[str, ...]
    rejected_bot_concerns: tuple[RejectedConcern, ...]

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
        rejected = output.get("rejected_bot_concerns")
        if not isinstance(rejected, list):
            raise InvalidFactsError("rejected_bot_concerns is not a list")
        return cls(
            risky_areas=lists["risky_areas"],
            reviews_on_current_head=lists["reviews_on_current_head"],
            owning_team_author=flags["owning_team_author"],
            strong_familiarity=flags["strong_familiarity"],
            unresolved_substantive_concerns=lists["unresolved_substantive_concerns"],
            other_refusal_grounds=lists["other_refusal_grounds"],
            rejected_bot_concerns=tuple(RejectedConcern.from_output(item) for item in rejected),
        )


@dataclass(frozen=True, kw_only=True)
class RuledVerdict:
    verdict: Verdict
    risk: Risk
    issues: tuple[str, ...]
    upheld_rejections: tuple[str, ...] = ()


def derive_verdict(facts: ReviewFacts, reviewing_bots: frozenset[str] = frozenset()) -> RuledVerdict:
    """Apply the review guidance's decision rule to the reported facts.

    Refusal grounds and unresolved concerns refuse anywhere. Risky territory needs
    independent assurance: a current-head review, or an author on the owning team or
    with STRONG familiarity. Without any of them the PR escalates to a human.

    A reviewer bot's finding that the author rejected is resolved when the reviewer judged the
    rejection sound, the finding is outside the strict categories, and `reviewing_bots`, which the
    pipeline reads from GitHub's author types rather than from the model, holds the login that
    raised it. Every other rejected finding stays an unresolved concern.
    """
    open_rejections: list[str] = []
    upheld: list[str] = []
    for rejected in facts.rejected_bot_concerns:
        reason = rejected.why_open(reviewing_bots)
        if reason is None:
            upheld.append(f"@{bot_handle(rejected.bot)}: {rejected.concern} Rejection holds: {rejected.evidence}")
        else:
            open_rejections.append(f"@{bot_handle(rejected.bot)}: {rejected.concern} Still open, because {reason}.")
    issues = [*facts.unresolved_substantive_concerns, *open_rejections, *facts.other_refusal_grounds]
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
    return RuledVerdict(verdict=verdict, risk=risk, issues=tuple(issues), upheld_rejections=tuple(upheld))


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
        "rejected_bot_concerns": len(parsed.rejected_bot_concerns),
        "rejected_bot_concerns_holding": sum(r.rejection_holds for r in parsed.rejected_bot_concerns),
    }
