from collections.abc import Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

from .candidates import Candidate, change_percent

SEVERITY = {"blocked": 0, "broken": 1, "slow": 2, "signal": 3}
KINDS = ("error", "growth", "user_voice", "friction", "improvement")
SURFACES = ("app", "app sign-in", "onboarding", "website")
MUST_TELL = ("growth", "user_voice")
MIN_PEOPLE = 100
LEAD_MIN_PEOPLE = 250
LEAD_MIN_CHANGE = 100.0
MAX_STORIES = 3
MAX_BRIEFS = 3
MAX_GROUP = 3


@frozen
class Fact:
    ref: str
    candidates: tuple[Candidate, ...]
    kind: str
    severity: str
    surface: str
    what: str
    trend: str
    look_next: str

    @property
    def people(self) -> int:
        return int(sum(candidate.today for candidate in self.candidates))

    @property
    def is_new(self) -> bool:
        return all(candidate.change == "new" for candidate in self.candidates)

    @property
    def strength(self) -> float:
        if self.is_new:
            return float("inf")
        return max((change_percent(c.change) or 0.0 for c in self.candidates), default=0.0)


@frozen
class Plan:
    lead: tuple[Fact, ...]
    stories: tuple[tuple[Fact, ...], ...]
    briefs: tuple[Fact, ...]


def parse_facts(raw: object, candidates: Mapping[str, Candidate]) -> list[Fact]:
    items = raw.get("facts") if isinstance(raw, dict) else None
    facts: list[Fact] = []
    used: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ids = [i for i in item.get("ids") or [] if isinstance(i, str) and i in candidates and i not in used]
        if not ids:
            continue
        used.update(ids)
        facts.append(
            Fact(
                ref=f"f{len(facts) + 1}",
                candidates=tuple(candidates[i] for i in ids),
                kind=_choice(item.get("kind"), KINDS, "friction"),
                severity=_choice(item.get("severity"), tuple(SEVERITY), "signal"),
                surface=_choice(item.get("surface"), SURFACES, "app"),
                what=_text(item.get("what")),
                trend=_text(item.get("trend")),
                look_next=_text(item.get("look_next")),
            )
        )
    return facts


def _choice(value: Any, allowed: Sequence[str], default: str) -> str:
    return value if value in allowed else default


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _rank(fact: Fact) -> tuple[int, bool, bool, int]:
    return (SEVERITY[fact.severity], fact.surface == "website", not fact.is_new, -fact.people)


def _counts(fact: Fact) -> bool:
    return fact.kind not in ("error", "friction") or fact.severity == "blocked" or fact.people >= MIN_PEOPLE


def _can_lead(fact: Fact) -> bool:
    if fact.severity == "blocked":
        return True
    return (
        fact.severity == "broken"
        and fact.surface != "website"
        and fact.people >= LEAD_MIN_PEOPLE
        and fact.strength >= LEAD_MIN_CHANGE
    )


def build(facts: Sequence[Fact]) -> Plan | None:
    pool = sorted((fact for fact in facts if _counts(fact)), key=_rank)
    if not pool:
        return None
    lead = next((f for f in pool if _can_lead(f)), None) or next((f for f in pool if f.kind in MUST_TELL), pool[0])
    pool.remove(lead)
    slots: list[tuple[Fact, ...]] = []
    groups: dict[str, list[Fact]] = {}
    for fact in pool:
        if fact.kind == "error" and fact.severity == "broken":
            groups.setdefault(fact.surface, []).append(fact)
    for members in groups.values():
        if len(members) >= 2:
            slots.append(tuple(members[:MAX_GROUP]))
            pool = [fact for fact in pool if fact not in members[:MAX_GROUP]]
    for kind in MUST_TELL:
        candidates = sorted(
            (
                f
                for f in pool
                if f.kind == kind and f.surface != "website" and (kind != "growth" or f.people >= MIN_PEOPLE)
            ),
            key=lambda f: -f.people,
        )
        for fact in candidates[:1]:
            slots.append((fact,))
            pool.remove(fact)
    for fact in list(pool):
        if len(slots) >= MAX_STORIES:
            break
        if fact.surface != "website" and fact.kind != "improvement":
            slots.append((fact,))
            pool.remove(fact)
    slots.sort(key=lambda members: _rank(members[0]))
    stories = tuple(slots[:MAX_STORIES])
    told = {fact.ref for slot in stories for fact in slot}
    briefs = tuple(fact for fact in pool if fact.ref not in told)[:MAX_BRIEFS]
    return Plan(lead=(lead,), stories=stories, briefs=briefs)


def writer_input(plan: Plan, project: str) -> dict[str, Any]:
    def describe(fact: Fact) -> dict[str, Any]:
        return {
            "ref": fact.ref,
            "kind": fact.kind,
            "severity": fact.severity,
            "surface": fact.surface,
            "what": fact.what,
            "people": f"{fact.people:,} {fact.candidates[0].unit}",
            "trend": fact.trend,
            "look_next": fact.look_next,
        }

    return {
        "project": project,
        "window": "the last 24 hours, compared with the median of the same 24 hours in each of the last 4 weeks",
        "lead": [describe(fact) for fact in plan.lead],
        "stories": [
            {
                "facts": [describe(fact) for fact in slot],
                "total_people": sum(f.people for f in slot) if len(slot) > 1 else None,
            }
            for slot in plan.stories
        ],
        "briefs": [describe(fact) for fact in plan.briefs],
    }
