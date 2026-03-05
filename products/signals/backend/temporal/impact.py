from dataclasses import dataclass, field
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.temporal.types import SignalData

SEVERITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class ReportImpactAssessment:
    # User breadth
    users_affected: int | None = None
    active_users_in_period: int | None = None
    user_impact_ratio: float | None = None

    # Occurrence frequency
    total_occurrences: int = 0
    external_report_count: int = 0

    # Source diversity
    source_products: list[str] = field(default_factory=list)
    cross_product_corroboration: bool = False

    # Severity
    strongest_external_severity: str | None = None
    severity_details: list[str] = field(default_factory=list)

    # Recency and trend
    most_recent_signal: str = ""
    earliest_signal: str = ""
    signals_per_day: float = 0.0


def extract_severity(signal: SignalData) -> str | None:
    extra = signal.extra
    match signal.source_product:
        case "zendesk":
            prio = extra.get("priority")
            return {"urgent": "urgent", "high": "high", "normal": "medium", "low": "low"}.get(prio)
        case "linear":
            prio = extra.get("priority")
            return {1: "urgent", 2: "high", 3: "medium", 4: "low"}.get(prio)
        case "github":
            labels = [item.lower() if isinstance(item, str) else "" for item in extra.get("labels", [])]
            for label in labels:
                if any(kw in label for kw in ("critical", "blocker", "p0", "urgent")):
                    return "urgent"
                if any(kw in label for kw in ("high", "p1", "important")):
                    return "high"
            return None
        case _:
            return None


def _count_distinct_persons(team: Team, distinct_ids: list[str]) -> int:
    if not distinct_ids:
        return 0
    result = execute_hogql_query(
        query_type="DistinctPersonCount",
        query=parse_select(
            """
            SELECT COUNT(DISTINCT person_id)
            FROM person_distinct_ids
            WHERE distinct_id IN {distinct_ids}"""
        ),
        placeholders={"distinct_ids": ast.Constant(value=distinct_ids)},
        team=team,
    )
    return result.results[0][0] if result.results and len(result.results) > 0 else 0


def compute_impact_assessment(team: Team, signals: list[SignalData]) -> ReportImpactAssessment:
    assessment = ReportImpactAssessment()

    # --- User breadth from session replay ---
    session_replay_distinct_ids: list[str] = []
    active_users_values: list[int] = []

    for signal in signals:
        if signal.source_product == "session_replay":
            for segment in signal.extra.get("segments", []):
                did = segment.get("distinct_id")
                if did:
                    session_replay_distinct_ids.append(did)
            active = signal.extra.get("metrics", {}).get("active_users_in_period")
            if active is not None:
                active_users_values.append(active)

    if session_replay_distinct_ids:
        assessment.users_affected = _count_distinct_persons(team, list(set(session_replay_distinct_ids)))
        if active_users_values:
            assessment.active_users_in_period = max(active_users_values)
            if assessment.active_users_in_period > 0:
                assessment.user_impact_ratio = assessment.users_affected / assessment.active_users_in_period

    # --- Occurrence frequency ---
    total_occurrences = 0
    for signal in signals:
        if signal.source_product == "session_replay":
            total_occurrences += signal.extra.get("metrics", {}).get("occurrence_count", 1)
        else:
            total_occurrences += 1
    assessment.total_occurrences = total_occurrences

    # --- External report count ---
    assessment.external_report_count = sum(1 for s in signals if s.source_product in ("github", "zendesk", "linear"))

    # --- Source diversity ---
    assessment.source_products = sorted({s.source_product for s in signals})
    assessment.cross_product_corroboration = len(assessment.source_products) >= 2

    # --- Severity ---
    severity_details: list[str] = []
    strongest: str | None = None

    # Collect per-source severity counts for details
    zendesk_severities: dict[str, int] = {}
    linear_details: list[str] = []
    github_severity: str | None = None

    for signal in signals:
        sev = extract_severity(signal)
        if sev is None:
            continue

        if strongest is None or SEVERITY_ORDER.get(sev, 99) < SEVERITY_ORDER.get(strongest, 99):
            strongest = sev

        match signal.source_product:
            case "zendesk":
                zendesk_severities[sev] = zendesk_severities.get(sev, 0) + 1
            case "linear":
                identifier = signal.extra.get("identifier", "Linear issue")
                priority_label = signal.extra.get("priority_label", sev)
                linear_details.append(f"{identifier} priority '{priority_label}'")
            case "github":
                if github_severity is None or SEVERITY_ORDER.get(sev, 99) < SEVERITY_ORDER.get(github_severity, 99):
                    github_severity = sev

    for sev, count in sorted(zendesk_severities.items(), key=lambda x: SEVERITY_ORDER.get(x[0], 99)):
        severity_details.append(f"{count} Zendesk ticket{'s' if count != 1 else ''} marked '{sev}'")
    for detail in linear_details:
        severity_details.append(detail)
    if github_severity:
        github_count = sum(1 for s in signals if s.source_product == "github" and extract_severity(s) is not None)
        severity_details.append(
            f"{github_count} GitHub issue{'s' if github_count != 1 else ''} with '{github_severity}' labels"
        )

    assessment.strongest_external_severity = strongest
    assessment.severity_details = severity_details

    # --- Recency and trend ---
    timestamps = sorted(_parse_timestamp(s.timestamp) for s in signals)
    if timestamps:
        assessment.most_recent_signal = timestamps[-1].isoformat()
        assessment.earliest_signal = timestamps[0].isoformat()
        span_days = max((timestamps[-1] - timestamps[0]).total_seconds() / 86400, 0.042)
        assessment.signals_per_day = len(signals) / span_days

    return assessment


def _parse_timestamp(ts: str) -> datetime:
    # Signal timestamps can come in various ISO formats
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def render_impact_assessment_to_text(assessment: ReportImpactAssessment) -> str:
    lines: list[str] = ["REPORT IMPACT ASSESSMENT:"]

    if assessment.users_affected is not None:
        if assessment.active_users_in_period and assessment.user_impact_ratio is not None:
            lines.append(
                f"- Users affected: {assessment.users_affected:,} of {assessment.active_users_in_period:,} "
                f"active users ({assessment.user_impact_ratio:.1%})"
            )
        else:
            lines.append(f"- Users affected: {assessment.users_affected:,}")
    else:
        lines.append("- Users affected: unknown (no session replay data)")

    lines.append(
        f"- Total occurrences: {assessment.total_occurrences:,} across {len(assessment.source_products)} "
        f"source{'s' if len(assessment.source_products) != 1 else ''}"
    )

    if assessment.external_report_count > 0:
        lines.append(f"- External reports: {assessment.external_report_count}")

    source_list = ", ".join(assessment.source_products)
    if assessment.cross_product_corroboration:
        lines.append(f"- Source diversity: {source_list} (cross-product corroboration)")
    else:
        lines.append(f"- Source diversity: {source_list}")

    if assessment.strongest_external_severity:
        detail_str = "; ".join(assessment.severity_details) if assessment.severity_details else ""
        lines.append(f"- Strongest external severity: {assessment.strongest_external_severity}")
        if detail_str:
            lines.append(f"  Details: {detail_str}")

    if assessment.signals_per_day > 0:
        span = _parse_timestamp(assessment.most_recent_signal) - _parse_timestamp(assessment.earliest_signal)
        span_days = max(span.total_seconds() / 86400, 0.042)
        if assessment.signals_per_day > 10:
            pattern = "active incident pattern"
        elif assessment.signals_per_day > 3:
            pattern = "elevated frequency"
        elif assessment.signals_per_day < 0.5:
            pattern = "chronic/slow accumulation"
        else:
            pattern = "moderate frequency"
        lines.append(f"- Trend: {assessment.signals_per_day:.1f} signals/day over {span_days:.1f} days ({pattern})")

    return "\n".join(lines)
