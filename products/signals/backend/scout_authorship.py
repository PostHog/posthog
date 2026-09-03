"""Which scout a report belongs to.

Authorship is recorded on the scout run rows that emitted or edited a report
(`SignalScoutRun.emitted_report_ids` / `edited_report_ids`). The inbox reads it off the signal
store in ClickHouse instead, but that read lags emit and can fail, so callers that must answer
on a request path resolve it from Postgres here.
"""

from __future__ import annotations

from django.db.models import Q

from products.signals.backend.models import SignalScoutRun
from products.skills.backend.models.skills import LLMSkill


def resolve_report_scout_skill(team_id: int, report_id: str) -> str:
    """The scout that owns one report, "" meaning the whole fleet.

    Thin single-report wrapper over `resolve_authoring_skill_names`.
    """
    return resolve_authoring_skill_names(team_id, [report_id]).get(report_id, "")


def resolve_touching_scout_skills(team_id: int, report_id: str) -> set[str]:
    """Every scout whose runs emitted or edited one report.

    The single-owner resolution below prefers the author, but a report's stored reviewers follow
    whichever scout last wrote them — possibly a later editor. Callers that exclude skill owners
    from autostart identity need the owners of every scout that could have produced the stored
    reviewers, so this returns the union of touching skills. Deleted skills are kept: their owner
    rows and stored picks can outlive the skill row, and over-exclusion is the safe direction.
    """
    # `for_team`, not an ambient-scope filter: the autostart caller runs in a Temporal activity,
    # which sets no team scope, and the fail-closed manager raises there.
    runs = SignalScoutRun.objects.for_team(team_id).filter(
        Q(emitted_report_ids__contains=[report_id]) | Q(edited_report_ids__contains=[report_id])
    )
    return {skill_name for skill_name in runs.values_list("skill_name", flat=True) if skill_name}


def resolve_authoring_skill_names(team_id: int, report_ids: list[str]) -> dict[str, str]:
    """Map every report id to the scout that owns it, "" meaning the fleet.

    A scout that only emitted the *signals* a report was later grouped from leaves no such row,
    and those reports get the fleet-wide target, where every scout still sees them.

    Two queries regardless of how many reports the caller asks about, because the alternative
    (containment lookup per report) is a scan of the team's runs per id.
    """
    if not report_ids:
        return {}

    touched = Q()
    for report_id in report_ids:
        touched |= Q(emitted_report_ids__contains=[report_id]) | Q(edited_report_ids__contains=[report_id])
    runs = (
        SignalScoutRun.objects.filter(team_id=team_id)
        .filter(touched)
        # Ascending so that when several runs touched the same report the newest one, applied last,
        # is the skill that ends up owning it.
        .order_by("created_at")
        .values_list("skill_name", "emitted_report_ids", "edited_report_ids")
    )

    wanted = set(report_ids)
    authored: dict[str, str] = {}
    edited: dict[str, str] = {}
    for skill_name, emitted_ids, edited_ids in runs:
        if not skill_name:
            continue
        for report_id in wanted.intersection(emitted_ids or []):
            authored[report_id] = skill_name
        for report_id in wanted.intersection(edited_ids or []):
            edited[report_id] = skill_name
    # Authorship wins over having merely edited the report: a scout that appended evidence to a
    # pipeline report is worth telling, but the scout that filed it is the one being judged.
    resolved = {report_id: authored.get(report_id) or edited.get(report_id, "") for report_id in report_ids}

    named = {skill_name for skill_name in resolved.values() if skill_name}
    # A note addressed to a skill that no longer exists steers no one, because the run-time read is
    # an exact match on the skill name (and `leave_note` rejects the target outright).
    live = (
        set(LLMSkill.objects.filter(team_id=team_id, name__in=named, deleted=False).values_list("name", flat=True))
        if named
        else set()
    )
    return {report_id: (skill_name if skill_name in live else "") for report_id, skill_name in resolved.items()}
