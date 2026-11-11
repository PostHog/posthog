"""The facts of a report that the scoring sweep records when it scores the report.

A fact is a raw value of the report, not a model input: the sources are the list of products, not
one-hot columns, so a later change to the source products needs no new history. The dataset dag's
`inbox_report_state` asset builds its shared columns through `report_content_annotations`,
`report_row_facts` and `judgment_facts`, so a column means the same on both sides. The two sides
differ only in when they read: the dag at the end of the report's first day, the sweep when it
scores the report.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from django.db.models import Case, CharField, F, Func, IntegerField, OuterRef, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.db.models.lookups import Exact

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.artefact_schemas import priority_from_judgment
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.signal_metadata import fetch_source_products_for_reports

# Bump when a fact is added, removed or read another way, so a reader of the events can tell the sets apart.
FACTS_SCHEMA_VERSION = 1

# The `SignalReport` fields `report_row_facts` reads, next to the `report_content_annotations`.
REPORT_FACT_FIELDS = (
    "signal_count",
    "total_weight",
    "run_count",
    "title",
    "summary",
    "content_revision_count",
    "corroboration_count",
    "user_authored",
)

JUDGMENT_TYPES = (
    SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
    SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
)

_SOURCES_READ_TIMEOUT_SECONDS = 30


@frozen
class ReportFacts:
    source_products: list[str]
    signal_count: int
    total_weight: float
    run_count: int
    content_revision_count: int
    corroboration_count: int
    title_chars: int
    summary_chars: int
    chart_count: int
    metric_count: int
    suggested_prompt_count: int
    tag_count: int
    user_authored: bool
    # None when the report has no judgment of that kind, or its latest one holds no usable value.
    priority: str | None
    actionability: str | None
    already_addressed: bool | None


def _json_array_length(field: str) -> Case:
    """Length of a JSON list column, computed in Postgres so the list itself is never loaded.
    `jsonb_array_length` raises on a value that is not an array, so any other stored value counts as 0."""
    return Case(
        When(
            Exact(Func(F(field), function="jsonb_typeof", output_field=CharField()), Value("array")),
            then=Func(F(field), function="jsonb_array_length", output_field=IntegerField()),
        ),
        default=Value(0),
        output_field=IntegerField(),
    )


def report_content_annotations() -> dict[str, Any]:
    """The `SignalReport` annotations that count the report's content, keyed by fact name."""
    return {
        "chart_count": _json_array_length("charts"),
        "metric_count": _json_array_length("metrics"),
        "suggested_prompt_count": _json_array_length("suggested_prompts"),
        "tag_count": Coalesce(Func(F("tags"), function="cardinality"), Value(0), output_field=IntegerField()),
    }


def report_row_facts(row: Mapping[str, Any]) -> dict[str, Any]:
    """The facts of one report row that holds `REPORT_FACT_FIELDS` and the `report_content_annotations`."""
    return {
        "signal_count": row["signal_count"],
        "total_weight": row["total_weight"],
        "run_count": row["run_count"],
        # The two counters have no default, and a scout write starts them from null. So null is a
        # report no scout has revised or corroborated yet, which every reader of the columns reads as 0.
        "content_revision_count": row["content_revision_count"] or 0,
        "corroboration_count": row["corroboration_count"] or 0,
        "title_chars": len(row["title"] or ""),
        "summary_chars": len(row["summary"] or ""),
        "chart_count": row["chart_count"],
        "metric_count": row["metric_count"],
        "suggested_prompt_count": row["suggested_prompt_count"],
        "tag_count": row["tag_count"],
        "user_authored": row["user_authored"],
    }


def _judgment_value(parsed: dict[str, Any], key: str) -> str | None:
    # Legacy artefact content is unconstrained JSON, so a value that is not a string is unknown. In
    # the dag, such a value would reach a pa.string() column and abort the whole partition build.
    value = parsed.get(key)
    return value if isinstance(value, str) else None


def _judgment_flag(parsed: dict[str, Any], key: str) -> bool | None:
    value = parsed.get(key)
    return value if isinstance(value, bool) else None


def no_judgment_facts() -> dict[str, Any]:
    """The judgment facts of a report with no usable judgment."""
    return {"priority": None, "actionability": None, "already_addressed": None}


def judgment_facts(artefact_type: str, content: str | None) -> dict[str, Any] | None:
    """The facts a priority or actionability judgment's content holds, or None when the content is not a JSON object.

    `already_addressed` comes from the actionability judgment, not from `SignalReport.latest_already_addressed`.
    """
    if artefact_type == SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT:
        return {"priority": priority_from_judgment(content)}
    try:
        parsed = json.loads(content or "")
    except ValueError:
        return None
    # Legacy artefact rows can hold JSON that is not an object.
    if not isinstance(parsed, dict):
        return None
    return {
        "actionability": _judgment_value(parsed, "actionability"),
        "already_addressed": _judgment_flag(parsed, "already_addressed"),
    }


def _latest_judgment(artefact_type: str) -> Subquery:
    return Subquery(
        SignalReportArtefact.objects.filter(team_id=OuterRef("team_id"), report_id=OuterRef("id"), type=artefact_type)
        .order_by("-created_at")
        .values("content")[:1]
    )


def read_report_facts(team_id: int, report_ids: Sequence[str]) -> dict[str, ReportFacts]:
    """The current facts of the team's reports in `report_ids`, by report id.

    One Postgres read gets the report rows with their latest judgments, a primary key lookup gets the
    team, and one ClickHouse read gets the sources. A report id that is not one of the team's reports
    has no entry.
    """
    content = report_content_annotations()
    rows = list(
        SignalReport.objects.filter(team_id=team_id, id__in=report_ids)
        .annotate(**content, **{artefact_type: _latest_judgment(artefact_type) for artefact_type in JUDGMENT_TYPES})
        .values("id", *REPORT_FACT_FIELDS, *content, *JUDGMENT_TYPES)
    )
    if not rows:
        return {}
    found = [str(row["id"]) for row in rows]
    sources = fetch_source_products_for_reports(
        Team.objects.get(id=team_id),
        found,
        ch_user=ClickHouseUser.SIGNALS,
        workload=Workload.OFFLINE,
        # Far below the sweep's time budget, so a slow read costs the facts events and not the later teams.
        max_execution_time=_SOURCES_READ_TIMEOUT_SECONDS,
    )
    facts: dict[str, ReportFacts] = {}
    for report_id, row in zip(found, rows):
        judgments = no_judgment_facts()
        for artefact_type in JUDGMENT_TYPES:
            judgments |= judgment_facts(artefact_type, row[artefact_type]) or {}
        meta = sources.get(report_id)
        facts[report_id] = ReportFacts(
            # No row is a report with no live signal.
            source_products=meta.source_products if meta else [],
            **report_row_facts(row),
            **judgments,
        )
    return facts
