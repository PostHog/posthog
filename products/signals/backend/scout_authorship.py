"""Which scout a report belongs to.

Authorship is recorded on the scout run rows that emitted or edited a report
(`SignalScoutRun.emitted_report_ids` / `edited_report_ids`). The inbox reads it off the signal
store in ClickHouse instead, but that read lags emit and can fail, so callers that must answer
on a request path resolve it from Postgres here.
"""

from __future__ import annotations

from django.db import connection
from django.db.models import BooleanField, Q, QuerySet
from django.db.models.expressions import RawSQL

from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.skills.backend.models.skills import LLMSkill


def resolve_report_scout_skill(team_id: int, report_id: str) -> str:
    """The scout that owns one report, "" meaning the whole fleet.

    Thin single-report wrapper over `resolve_authoring_skill_names`.
    """
    return resolve_authoring_skill_names(team_id, [report_id]).get(report_id, "")


def resolve_touching_scout_skills(team_id: int, report_id: str) -> list[str]:
    """Every scout whose runs emitted or edited one report, emitting scouts first.

    The single-owner resolution below prefers the author, but a report's stored reviewers follow
    whichever scout last wrote them — possibly a later editor. Callers that exclude skill owners
    from autostart identity, or that address each router of the report, need every touching skill,
    so this returns their union. Deleted skills are kept: their owner rows and stored picks can
    outlive the skill row, and over-exclusion is the safe direction for autostart. A caller that
    writes to the skills filters them itself.

    A caller that addresses each scout separately has to cap the list, so the order decides who is
    dropped: the scouts that filed the report come first, and each group is sorted, so the same
    report always resolves the same way.
    """
    # `for_team`, not an ambient-scope filter: the autostart caller runs in a Temporal activity,
    # which sets no team scope, and the fail-closed manager raises there.
    runs = SignalScoutRun.objects.for_team(team_id).filter(
        Q(emitted_report_ids__contains=[report_id]) | Q(edited_report_ids__contains=[report_id])
    )
    emitting: set[str] = set()
    editing: set[str] = set()
    for skill_name, emitted_ids in runs.values_list("skill_name", "emitted_report_ids"):
        if not skill_name:
            continue
        if report_id in (emitted_ids or []):
            emitting.add(skill_name)
        else:
            editing.add(skill_name)
    return [*sorted(emitting), *sorted(editing - emitting)]


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
        # `for_team`, not an ambient-scope filter: the default-owner caller runs in a Temporal
        # activity, which sets no team scope, and the fail-closed manager raises there.
        SignalScoutRun.objects.for_team(team_id)
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


BACKGROUND_RUN_METADATA = {"managed_by": SignalScoutConfig.ManagedBy.BACKGROUND}


def resolve_background_authoring_runs(team_id: int, report_ids: list[str]) -> dict[str, SignalScoutRun]:
    """Map each report a background-enrolled scout run authored to that run.

    Only authorship counts: a background scout that edited a user scout's report does not make the
    report a background one. The origin is the one stamped on the run at dispatch, so a person who
    later takes over, switches off, or deletes the config does not clear it.
    """
    if not report_ids:
        return {}
    authored = Q()
    for report_id in report_ids:
        authored |= Q(emitted_report_ids__contains=[report_id])
    runs = SignalScoutRun.objects.for_team(team_id).filter(authored, metadata__contains=BACKGROUND_RUN_METADATA)
    wanted = set(report_ids)
    resolved: dict[str, SignalScoutRun] = {}
    for run in runs:
        for report_id in wanted.intersection(run.emitted_report_ids or []):
            resolved[report_id] = run
    return resolved


def report_is_from_background_scout(team_id: int, report_id: str) -> bool:
    return report_id in resolve_background_authoring_runs(team_id, [report_id])


def _inbox_opted_out_runs(team_id: int) -> QuerySet[SignalScoutRun]:
    # Matches `scout_lists_reports_in_inbox`: only an explicit `inbox: false` opts a scout out.
    opted_out_configs = SignalScoutConfig.objects.for_team(team_id).filter(output_destinations__inbox=False)
    return SignalScoutRun.objects.for_team(team_id).filter(scout_config_id__in=opted_out_configs.values("id"))


def inbox_hidden_report_filter(team_id: int) -> RawSQL:
    """Keeps a report out of the inbox list when the scout that authored it turned off its inbox destination.

    Only authorship counts, read from the config's current setting: an opted-out scout that edits
    another source's report does not hide it, and turning the scout back on lists its reports again.
    Use it in a filter on a `SignalReport` queryset. The `NOT EXISTS` correlates on plain equality
    with the report id, so Postgres plans it as an anti-join. A JSONB containment check, or a
    `NOT IN` over the expanded ids, can fall back to a probe once for each report in the team.
    """
    quote = connection.ops.quote_name
    # Trusted identifiers: from Django ORM metadata. Values are parameterized.
    runs = quote(SignalScoutRun._meta.db_table)
    configs = quote(SignalScoutConfig._meta.db_table)
    reports = quote(SignalReport._meta.db_table)
    sql = f"""NOT EXISTS (
        SELECT 1
        FROM {runs} AS hidden_run
        CROSS JOIN LATERAL jsonb_array_elements_text(hidden_run.emitted_report_ids) AS hidden(report_id)
        WHERE hidden_run.team_id = %s
          AND jsonb_typeof(hidden_run.emitted_report_ids) = 'array'
          AND hidden_run.scout_config_id IN (
              SELECT id FROM {configs} WHERE team_id = %s AND output_destinations -> 'inbox' = 'false'::jsonb
          )
          AND hidden.report_id = {reports}.id::text
    )"""
    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (identifiers from ORM metadata, values parameterized)
    return RawSQL(sql, (team_id, team_id), output_field=BooleanField())


def report_is_hidden_from_inbox(team_id: int, report_id: str) -> bool:
    return _inbox_opted_out_runs(team_id).filter(emitted_report_ids__contains=[report_id]).exists()
