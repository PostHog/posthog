from products.stamphog.backend.facade.enums import ReviewVerdict
from products.stamphog.backend.logic.reviewer import ReviewerVerdict


def warrants_deep_review(verdict: ReviewerVerdict) -> bool:
    if verdict.verdict not in (ReviewVerdict.REFUSED, ReviewVerdict.ESCALATE):
        return False
    result = verdict.gate_result
    if result.get("attestation"):
        return False
    if any(
        gate.get("gate") in {"size", "deny-list", "tier"} and gate.get("passed") is False
        for gate in result.get("gates", [])
        if isinstance(gate, dict)
    ):
        return True
    facts = result.get("reviewer_facts")
    if not isinstance(facts, dict):
        return False
    list_fields = ("risky_areas", "reviews_on_current_head", "unresolved_substantive_concerns", "other_refusal_grounds")
    return (
        all(
            isinstance(facts.get(key), list) and all(isinstance(value, str) for value in facts[key])
            for key in list_fields
        )
        and all(isinstance(facts.get(key), bool) for key in ("owning_team_author", "strong_familiarity"))
        and any(value.strip() for value in facts["risky_areas"])
    )
