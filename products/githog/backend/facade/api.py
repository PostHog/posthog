"""
Facade for githog.

This is the ONLY module other products are allowed to import.

Responsibilities:
- Accept frozen dataclasses as input parameters
- Call business logic (logic.py)
- Convert Django models to frozen dataclasses before returning
- Enforce transactions where needed
- Remain thin and stable

Do NOT:
- Implement business logic here (use logic.py)
- Import DRF, serializers, or HTTP concerns
"""

from typing import TYPE_CHECKING

from ..logic.dashboard_refs import find_referencing_insights_and_dashboards
from ..logic.diff_scanner import (
    extract_changed_files,
    extract_event_names,
    extract_flag_keys,
    extract_known_event_mentions,
    extract_known_flag_mentions,
)
from ..logic.event_reach import compute_per_event_reach
from ..logic.flag_reach import compute_intersection_reach, compute_per_flag_reach
from ..logic.issue_refs import find_referencing_issues
from ..logic.known_keys import fetch_team_event_names, fetch_team_flag_keys
from ..logic.llm_orchestrator import run_orchestrator
from ..logic.related_signals import find_related_signals
from ..logic.web_paths import compute_pageview_reach, extract_url_paths_from_diff
from .contracts import EventReference, FlagReference, PRImpactReport, PRImpactRequest

if TYPE_CHECKING:
    from posthog.models import Team


def _merge_flag_references(*groups: list[FlagReference]) -> list[FlagReference]:
    """Union flag references across detection passes.

    For a given key: union file paths, sum occurrences. Const references
    (`const:X`) are kept as-is and not merged with concrete keys.
    """
    by_key: dict[str, tuple[set[str], int]] = {}
    for group in groups:
        for ref in group:
            paths, count = by_key.get(ref.key, (set(), 0))
            paths.update(ref.file_paths)
            count += ref.occurrences
            by_key[ref.key] = (paths, count)

    merged = [
        FlagReference(key=key, file_paths=tuple(sorted(paths)), occurrences=count)
        for key, (paths, count) in by_key.items()
    ]
    merged.sort(key=lambda r: (-r.occurrences, r.key))
    return merged


def _merge_event_references(*groups: list[EventReference]) -> list[EventReference]:
    """Union event references across detection passes — same shape as flags."""
    by_name: dict[str, tuple[set[str], int]] = {}
    for group in groups:
        for ref in group:
            paths, count = by_name.get(ref.name, (set(), 0))
            paths.update(ref.file_paths)
            count += ref.occurrences
            by_name[ref.name] = (paths, count)

    merged = [
        EventReference(name=name, file_paths=tuple(sorted(paths)), occurrences=count)
        for name, (paths, count) in by_name.items()
    ]
    merged.sort(key=lambda r: (-r.occurrences, r.name))
    return merged


def compute_pr_impact(team: "Team", request: PRImpactRequest) -> PRImpactReport:
    """Score the user-facing impact of a PR diff.

    Two detection passes are unioned:
      1. SDK call-shape regex — `posthog.capture(...)`, `isFeatureEnabled(...)`, etc.
      2. Known-key/name scan — string literals matching the team's actual flag keys
         and recent event names. Catches references the call-shape regex misses
         (wrapped clients, const-indirected keys, config-driven lookups).

    Reach is then measured empirically over the lookback window.
    """
    # --- Flags: call-shape + known-key passes ---------------------------------
    regex_flag_refs = extract_flag_keys(request.diff_text)
    known_flag_keys = fetch_team_flag_keys(team)
    known_flag_refs = extract_known_flag_mentions(request.diff_text, known_flag_keys)

    flag_references = _merge_flag_references(regex_flag_refs, known_flag_refs)

    # Constants (FEATURE_FLAGS.X) cannot be resolved to string keys statically,
    # so they're surfaced for the reviewer but excluded from the reach query.
    queryable_keys = [r.key for r in flag_references if not r.key.startswith("const:")]

    notes: list[str] = []
    unresolved_consts = [r.key for r in flag_references if r.key.startswith("const:")]
    if unresolved_consts:
        notes.append(
            f"{len(unresolved_consts)} flag reference(s) use constants — "
            f"resolve them in code to get reach: {', '.join(unresolved_consts)}"
        )

    per_flag = compute_per_flag_reach(team, queryable_keys, request.lookback_days)
    flags_no_data = [f.key for f in per_flag if not f.has_data]
    if flags_no_data:
        notes.append(
            f"{len(flags_no_data)} flag(s) have no recent evaluations — reach unknown, not zero: {', '.join(flags_no_data)}"
        )

    intersection_users, intersection_sessions = compute_intersection_reach(team, queryable_keys, request.lookback_days)

    # --- Events: call-shape + known-name passes --------------------------------
    regex_event_refs = extract_event_names(request.diff_text)
    known_event_names = fetch_team_event_names(team, lookback_days=max(request.lookback_days, 90))
    known_event_refs = extract_known_event_mentions(request.diff_text, known_event_names)

    event_references = _merge_event_references(regex_event_refs, known_event_refs)
    event_names = [r.name for r in event_references]
    per_event = compute_per_event_reach(team, event_names, request.lookback_days)
    events_no_data = [e.name for e in per_event if not e.has_data]
    if events_no_data:
        notes.append(
            f"{len(events_no_data)} event(s) have no recent activity — reach unknown, not zero: {', '.join(events_no_data)}"
        )

    # --- Dashboards / insights referencing any matched key/name --------------
    flag_terms = [r.key for r in flag_references if not r.key.startswith("const:")]
    event_terms = [r.name for r in event_references]
    dashboard_references = find_referencing_insights_and_dashboards(team, flag_terms + event_terms)

    # --- Error Tracking issues implicating this PR ---------------------------
    changed_files = extract_changed_files(request.diff_text)
    issue_references = find_referencing_issues(
        team,
        changed_files=changed_files,
        key_terms=flag_terms + event_terms,
        lookback_days=request.lookback_days,
    )

    # --- Related signals: filename-token fuzzy match against known keys/names -
    # Catches PRs that don't literally reference any flag/event but clearly
    # touch named business logic. Skips anything already confirmed above.
    related_signals = find_related_signals(
        team,
        changed_files=changed_files,
        known_flag_keys=known_flag_keys,
        known_event_names=known_event_names,
        lookback_days=request.lookback_days,
        exclude_flag_keys=set(flag_terms),
        exclude_event_names=set(event_terms),
    )

    # --- Web analytics: URL paths in the diff -------------------------------
    path_candidates = extract_url_paths_from_diff(request.diff_text)
    web_paths = compute_pageview_reach(team, path_candidates, request.lookback_days)

    # --- LLM synthesis: tool-use loop over the deterministic results --------
    # Soft-fail: missing API key or transport errors return None and the rest
    # of the report renders without the AI section.
    llm_analysis = run_orchestrator(
        team,
        diff_text=request.diff_text,
        changed_files=changed_files,
        lookback_days=request.lookback_days,
        known_flag_keys=known_flag_keys,
        known_event_names=known_event_names,
        flag_references=flag_references,
        per_flag_reach=per_flag,
        event_references=event_references,
        per_event_reach=per_event,
        related_signals=related_signals,
        dashboard_references=dashboard_references,
        issue_references=issue_references,
        web_paths=web_paths,
    )

    return PRImpactReport(
        flag_references=tuple(flag_references),
        per_flag_reach=tuple(per_flag),
        intersection_users=intersection_users,
        intersection_sessions=intersection_sessions,
        lookback_days=request.lookback_days,
        event_references=tuple(event_references),
        per_event_reach=tuple(per_event),
        dashboard_references=tuple(dashboard_references),
        issue_references=tuple(issue_references),
        related_signals=tuple(related_signals),
        web_paths=tuple(web_paths),
        changed_files=tuple(changed_files),
        known_flag_count=len(known_flag_keys),
        known_event_count=len(known_event_names),
        llm_analysis=llm_analysis,
        notes=tuple(notes),
    )
