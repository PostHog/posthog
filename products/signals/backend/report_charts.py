"""The charts a report carries: schema, bounds, and the refusals a chart query has to pass.

A chart is part of a report's content, not an entry in its log — it lives on `SignalReport.charts`
alongside the title and summary it illustrates, and the summary places it with a
`[label](chart:<chart_id>)` link. Kept out of `artefact_schemas.py` for that reason, and kept as
dependency-light as that module for the same one: it loads with the signals models, so it must not
drag `posthog.schema` onto every process's `django.setup()` path.
"""

from __future__ import annotations

import re
import json
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# The slug is the target of a `chart:` markdown link, so it has to survive being parsed as a URL.
# Mirrors the routing-safe identifier shape used across the signals schemas, inlined to keep this
# module free of cross-imports.
_CHART_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Query node kinds a chart may carry — the three the inbox renderer knows how to draw. Narrow on
# purpose: an unrenderable kind fails at write time, where the author can react to it, rather than
# silently drawing nothing in someone's inbox a day later.
CHART_QUERY_KINDS: frozenset[str] = frozenset({"InsightVizNode", "DataVisualizationNode", "SavedInsightNode"})

# How many charts one report may carry. Bounds how many queries a report fires when it's opened.
# Roughly a dashboard's worth: enough for a report to actually show its working, and in the same
# range of concurrent queries an opened dashboard already costs.
MAX_REPORT_CHARTS = 20

# Total serialized `query` JSON one report may carry. The safety judge is shown every chart supplied
# in a call, query bodies included, so `MAX_REPORT_CHARTS * _MAX_CHART_QUERY_CHARS` is what that
# prompt would cost in the worst case — which is why the batch needs its own bound and not just the
# per-chart one. Generous against real nodes, which run a few hundred to a few thousand characters.
MAX_REPORT_CHARTS_QUERY_CHARS = 60_000

MAX_CHART_ID_LENGTH = 100
MAX_CHART_TITLE_LENGTH = 200
MAX_CHART_CAPTION_LENGTH = 500

# How tall a chart draws in the report body. Three named steps rather than a pixel height: the report
# column is responsive and the author is writing from a sandbox, so it can pick the weight a chart
# should carry but not the space it will have. Left unset, the renderer infers a step from the node
# (a single big number needs a fraction of what a retention grid does).
ChartSize = Literal["small", "medium", "large"]
CHART_SIZES: tuple[ChartSize, ...] = ("small", "medium", "large")

# Bounds the JSON a single chart can carry into the report and, from there, into the safety-judge
# prompt. Generous next to a real query node; small enough that a malformed one can't blow up a call.
_MAX_CHART_QUERY_CHARS = 20_000

# Bounds nesting so the size check below can serialize at all. `json.dumps` recurses, and past
# CPython's limit it raises `RecursionError` — which pydantic does not fold into a `ValidationError`,
# so it escapes the write path as a 500 instead of a 400. Deep enough that no real query node comes
# close, shallow enough that serializing one stays well inside the limit.
_MAX_CHART_QUERY_DEPTH = 100

# Query kinds whose payload is a program rather than a description of data. The renderer hands a
# node's nested source straight to the query service, and `HogQuery` is the branch there that runs
# its `code` through `execute_hog`. `SuggestedQuestionsQuery` is not an interpreter but bills like
# one: its runner calls `hit_openai`, so a report carrying it spends money on the reader's behalf
# every time someone opens it, times the chart cap.
_EXECUTABLE_QUERY_KINDS = frozenset({"HogQuery", "SuggestedQuestionsQuery"})


def _nests_too_deeply(value: Any) -> bool:
    """Whether a query nests past `_MAX_CHART_QUERY_DEPTH`, walked on an explicit stack.

    Runs before the serialized-size check because that check is the thing that cannot survive deep
    input: measuring the size means serializing it first, and `json.dumps` blows the stack on a
    query far smaller than the size bound would ever reject.
    """
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > _MAX_CHART_QUERY_DEPTH:
            return True
        if isinstance(item, dict):
            pending.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            pending.extend((nested, depth + 1) for nested in item)
    return False


def _unstorable_text(value: Any) -> str | None:
    """What a query holds that cannot reach the `charts` column, or None if it can all be stored.

    Two characters survive JSON parsing but not the trip to Postgres, and both arrive as ordinary
    caller input: a null character, which `jsonb` cannot hold, and an unpaired UTF-16 surrogate
    (`"\\ud800"`), which Python decodes happily but cannot encode back to UTF-8 for the wire. Either
    one fails at the write, past every handler that turns bad input into a 400.

    Walked over the decoded structure rather than the serialized JSON: `json.dumps` writes a real
    null as the six characters `\\u0000`, but it writes the *literal* text `\\u0000` as `\\\\u0000`,
    which contains that same sequence — so a substring test on the serialized form also rejects a
    query that merely spells the escape out (HogQL searching for it, say). Keys as well as values,
    since a key reaches the same `jsonb` column.
    """
    pending: list[Any] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if "\x00" in item:
                return "a null character"
            if any("\ud800" <= char <= "\udfff" for char in item):
                return "an unpaired surrogate"
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return None


def _executable_payload(value: Any) -> str | None:
    """What a query node carries that something downstream would *run*, or None if nothing does.

    The `kind` allowlist only covers the outer node, and four shapes reach something expensive from
    underneath it, each on a different reader's behalf:

    - `bytecode`: a `DataVisualizationNode` can hold `tableSettings.conditionalFormatting[*].bytecode`,
      which the table renderer feeds to `execHog` once per rendered cell, synchronously, on the
      reader's main thread. HogVM bounds one call at five seconds, but the cost multiplies by cell
      count, so a chart carrying expensive bytecode freezes the tab of whoever opens the report.
    - a nested `HogQuery`: the renderer posts a node's source to the query service as its data node,
      where `process_query_model` runs `code` through `execute_hog` (staff-only on cloud, but any
      reader on a self-hosted deployment).
    - `sendRawQuery`: with a `connectionId`, `HogQLQueryRunner` skips the HogQL printer and sends the
      query text verbatim to the external engine, under the session of whoever opened the report. A
      `connectionId` on its own still goes through the printer and the resource access check, so it
      stays allowed — it's the raw-SQL bypass that turns a chart into someone else's shell.

    - a nested `SuggestedQuestionsQuery`: an allowed outer node auto-loads its source, and that
      runner calls `hit_openai`, so opening the report buys an LLM completion per chart. Refused for
      cost rather than execution, but it reaches the same place: work the reader never asked for.

    A chart is a picture of a query, not a program, so all four are refused wherever they sit rather
    than only at the paths known today. Enumerating hazards this way loses to an allowlist of
    renderable source kinds; that is the durable shape, and a wider change than adding a refusal.

    Walks an explicit stack rather than recursing: the query is caller-supplied and only bounded by
    its serialized size, so a few hundred nested objects fit well inside that bound while a recursive
    scan would raise `RecursionError` — an uncaught 500 out of a validator whose whole job is to
    answer with a 400.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if any(key == "bytecode" and nested for key, nested in item.items()):
                return "`bytecode`"
            if item.get("sendRawQuery"):
                return "`sendRawQuery`"
            kind = item.get("kind")
            # `kind` is caller-supplied JSON and can be unhashable; check it's a string before the
            # membership test so a bad write stays a 400 rather than a TypeError out of the validator.
            if isinstance(kind, str) and kind in _EXECUTABLE_QUERY_KINDS:
                return f"a nested `{kind}`"
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return None


class ReportChart(BaseModel):
    """One chart on a report: a query the inbox renders in the report body.

    `chart_id` is the author's own slug rather than a generated id, because a report's summary and
    its charts are written in the same call — prose can only point at a chart by a key the author
    picked. It mirrors `evidence.source_id` on the scout report channel.

    A report's `charts` is the full set it currently shows: writing them replaces what was there,
    the way writing `summary` does. Ids are unique within that set, so a reference resolves to
    exactly one chart with no ordering rule to apply.

    `query` stays an unparsed dict. Checking it against the real node models would mean importing
    `posthog.schema`, which this module deliberately avoids (see the module docstring). The `kind`
    allowlist and the size bound are what can be checked cheaply here — the same amount of validation
    a notebook's `ph-query` node gets today, with the renderer degrading in place on a bad query.
    """

    chart_id: str = Field(
        description=(
            "Stable slug identifying this chart within the report — lowercase letters, numbers, "
            "underscores and hyphens. The report summary references it as a markdown link with a "
            "`chart:` target (e.g. `[Daily signups](chart:signups-drop)`) to place the chart inline."
        ),
    )
    title: str = Field(description="Short heading shown above the chart.")
    query: dict[str, Any] = Field(
        description=(
            "The query node to render, as JSON. `kind` must be one of `InsightVizNode`, "
            "`DataVisualizationNode`, or `SavedInsightNode`. Pin the window to absolute dates where "
            "the node supports it, so a reader sees the data the report was written about rather than "
            "whatever the range resolves to when they open it."
        ),
    )
    caption: str | None = Field(
        default=None,
        description="Optional one-line note on what to look at in the chart.",
    )
    size: ChartSize | None = Field(
        default=None,
        description=(
            "How much vertical space the chart gets: `small` for a single number or a short series, "
            "`medium` for an ordinary graph, `large` for something with rows or a grid to read "
            "(retention, paths, a wide breakdown). Leave unset to let the inbox size it from the "
            "query, which is right for most charts."
        ),
    )

    @field_validator("chart_id")
    @classmethod
    def chart_id_must_be_reference_safe(cls, v: str) -> str:
        if len(v) > MAX_CHART_ID_LENGTH:
            raise ValueError(f"must not exceed {MAX_CHART_ID_LENGTH} characters")
        normalized = v.strip()
        if not _CHART_ID_RE.fullmatch(normalized):
            raise ValueError(
                "must contain only lowercase letters, numbers, underscores, or hyphens, "
                "and must start with a lowercase letter or number"
            )
        return normalized

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        if len(v) > MAX_CHART_TITLE_LENGTH:
            raise ValueError(f"must not exceed {MAX_CHART_TITLE_LENGTH} characters")
        return v

    @field_validator("caption")
    @classmethod
    def caption_must_be_bounded(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_CHART_CAPTION_LENGTH:
            raise ValueError(f"must not exceed {MAX_CHART_CAPTION_LENGTH} characters")
        return v

    @field_validator("query")
    @classmethod
    def query_must_be_a_renderable_node(cls, v: dict[str, Any]) -> dict[str, Any]:
        kind = v.get("kind")
        # `kind` is caller-supplied JSON, so it can be any type. Check it's a string before the
        # membership test — an unhashable one (`{"kind": []}`) would raise TypeError out of the
        # validator, escaping the ValidationError path that turns a bad write into a 400.
        if not isinstance(kind, str) or kind not in CHART_QUERY_KINDS:
            allowed = ", ".join(sorted(CHART_QUERY_KINDS))
            raise ValueError(f"query.kind must be one of {allowed} (got {kind!r})")
        if _nests_too_deeply(v):
            raise ValueError(f"query must not nest deeper than {_MAX_CHART_QUERY_DEPTH} levels")
        try:
            serialized = json.dumps(v, allow_nan=False)
        except ValueError:
            # `NaN` and `Infinity` are not JSON, but the project parses requests with DRF's
            # STRICT_JSON off, so a caller can put one in a query and `json.dumps` will happily
            # write it back out. Postgres `jsonb` then refuses the INSERT, past every handler that
            # turns bad input into a 400.
            raise ValueError("query must not contain a non-finite number") from None
        if len(serialized) > _MAX_CHART_QUERY_CHARS:
            raise ValueError(f"query must not exceed {_MAX_CHART_QUERY_CHARS} characters when serialized")
        unstorable = _unstorable_text(v)
        if unstorable:
            raise ValueError(f"query must not contain {unstorable}")
        executable = _executable_payload(v)
        if executable:
            raise ValueError(f"query must not carry {executable} — a chart renders data, it does not run code")
        return v


def chart_batch_query_chars(charts: Sequence[ReportChart]) -> int:
    """Serialized size of a set of charts' queries, for `MAX_REPORT_CHARTS_QUERY_CHARS`."""
    return sum(len(json.dumps(chart.query)) for chart in charts)


def chart_batch_error(charts: Sequence[ReportChart]) -> str | None:
    """Why a set of charts can't be stored together, or None if it can.

    A `ReportChart` field validator already vets each chart's shape; this is the whole-set contract
    no single chart can enforce — the count cap, the combined query-size budget, and `chart_id`
    uniqueness. All three are decided from the payload alone, so a caller writing charts from any
    authoring surface (a scout tool, the research pipeline) shares one contract rather than
    restating the checks. Uniqueness matters because the inbox indexes a report's charts by id: two
    charts under one id collapse to whichever is last, so a `chart:` reference draws the wrong query
    and the other chart silently vanishes.
    """
    if len(charts) > MAX_REPORT_CHARTS:
        return f"a report accepts at most {MAX_REPORT_CHARTS} charts ({len(charts)})"
    total_query_chars = chart_batch_query_chars(charts)
    if total_query_chars > MAX_REPORT_CHARTS_QUERY_CHARS:
        # Echo the actual total, not just the limit: a scout agent reads this error off its
        # emit_report / edit_report tool call and needs to know how far over budget it is to trim
        # and retry. The total is already computed for the comparison, so including it is free.
        return (
            f"the charts' queries total {total_query_chars} characters, "
            f"the limit is {MAX_REPORT_CHARTS_QUERY_CHARS} across one report"
        )
    seen: set[str] = set()
    for chart in charts:
        if chart.chart_id in seen:
            return f"duplicate chart_id {chart.chart_id!r} — chart_ids must be unique within a report"
        seen.add(chart.chart_id)
    return None
