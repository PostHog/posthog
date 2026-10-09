"""The shapes a dashboard import passes between the parser, the agent, the validator and the tile builder.

They are pydantic models because the import stores them as JSON in the task state, attaches them to
the agent run, and reads the agent's answer back.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GRID_COLUMNS = 12

ImportSource = Literal["grafana", "screenshot"]
PanelKind = Literal[
    "timeseries", "stat", "gauge", "bargauge", "table", "heatmap", "text", "row", "logs", "traces", "unsupported"
]
DisplayType = Literal["line", "area", "bar", "stat", "gauge", "bargauge", "table", "heatmap"]
Reducer = Literal["last", "mean", "min", "max", "sum", "delta"]
TargetLanguage = Literal["promql", "logql", "traceql", "other"]
PanelOutcome = Literal["imported", "approximated", "failed", "skipped"]
QueryLanguage = Literal["promql", "builder", "histogram", "hogql"]
Aggregation = Literal["sum", "avg", "count", "min", "max", "p95", "rate", "increase", "histogram_quantile"]
FilterOperator = Literal["eq", "neq", "regex", "not_regex"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GridLayout(_Model):
    """A tile box on the 12-column dashboard grid."""

    x: int = Field(description="Column of the left edge, from 0 to 11.")
    y: int = Field(description="Row of the top edge, from 0.")
    w: int = Field(description="Width in columns, from 1 to 12.")
    h: int = Field(description="Height in rows. One row is about 80 pixels.")

    def clamped(self, *, min_w: int = 1, min_h: int = 1) -> GridLayout:
        w = min(max(self.w, min_w), GRID_COLUMNS)
        x = min(max(self.x, 0), GRID_COLUMNS - w)
        return GridLayout(x=x, y=max(self.y, 0), w=w, h=max(self.h, min_h))


class Threshold(_Model):
    color: str = Field(
        description="Color token: success, warning, danger, blue, purple, or data-color-1 to data-color-15."
    )
    value: float = Field(description="Lower bound of the band. The lowest band also colors every lower value.")


class DisplaySpec(_Model):
    type: DisplayType = Field(default="line", description="How the panel draws its data.")
    unit: str | None = Field(default=None, description='UCUM unit, for example "s", "ms", "By", "%", "{req}/s".')
    reduce: Reducer | None = Field(default=None, description="How stat, gauge and table panels reduce a series.")
    thresholds: list[Threshold] = Field(default_factory=list, description="Color bands for stat and gauge panels.")
    min: float | None = Field(default=None, description="Lower end of the axis or gauge.")
    max: float | None = Field(default=None, description="Upper end of the axis or gauge.")
    log_scale: bool = Field(default=False, description="Use a logarithmic y-axis.")


class TargetSpec(_Model):
    ref_id: str
    language: TargetLanguage
    datasource_type: str | None = None
    expr: str
    original_expr: str
    legend: str | None = None
    unresolved_variables: list[str] = Field(default_factory=list)


class PanelSpec(_Model):
    key: str
    title: str
    description: str = ""
    kind: PanelKind
    grafana_type: str
    layout: GridLayout
    display: DisplaySpec = Field(default_factory=DisplaySpec)
    targets: list[TargetSpec] = Field(default_factory=list)
    text: str | None = None
    notes: list[str] = Field(default_factory=list)
    skip_reason: str | None = None


class DashboardSpec(_Model):
    title: str
    description: str = ""
    date_from: str | None = None
    panels: list[PanelSpec]
    variables: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class BuilderFilter(_Model):
    key: str = Field(description="Attribute name, for example service.name or http.route.")
    op: FilterOperator = Field(description="Comparison. regex and not_regex use RE2 syntax.")
    value: str


class BuilderClause(_Model):
    name: str = Field(description='Alias that a formula uses, for example "a".')
    metric_name: str = Field(description="Exact metric name from the catalog.")
    aggregation: Aggregation
    quantile: float | None = Field(
        default=None, description="A value between 0 and 1. Only histogram_quantile uses it."
    )
    filters: list[BuilderFilter] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list, description="Attribute names that split the series.")


class BuilderQuery(_Model):
    clauses: list[BuilderClause]
    formula: str | None = Field(default=None, description='Arithmetic over clause aliases, for example "a / b".')


class PanelQuery(_Model):
    language: QueryLanguage = Field(
        description="promql for metrics when PromQL is available, builder for metrics when it is not, "
        "histogram for a latency heatmap, hogql for logs and traces."
    )
    promql: str | None = Field(default=None, description="The PromQL expression when language is promql.")
    builder: BuilderQuery | None = Field(default=None, description="The builder query when language is builder.")
    histogram_metric: str | None = Field(
        default=None, description="The histogram metric name when language is histogram."
    )
    hogql: str | None = Field(
        default=None, description="A SQL SELECT over logs or posthog.trace_spans when language is hogql."
    )


class AgentPanel(_Model):
    key: str = Field(description="The panel key from the brief, or a new key such as s1 for a screenshot panel.")
    title: str
    outcome: PanelOutcome = Field(
        description="imported: same meaning. approximated: works but the meaning changed. "
        "failed: no working query. skipped: no PostHog equivalent."
    )
    reason: str = Field(description="What changed or why it failed. Empty when the panel imported exactly.")
    query: PanelQuery | None = Field(default=None, description="The query for an imported or approximated panel.")
    display: DisplaySpec | None = Field(default=None, description="Required for a screenshot panel.")
    layout: GridLayout | None = Field(default=None, description="Required for a screenshot panel.")
    text: str | None = Field(default=None, description="Markdown for a text panel in a screenshot.")


class AgentImportOutput(_Model):
    dashboard_name: str = Field(description="A short name for the dashboard.")
    panels: list[AgentPanel]


class TileDraft(_Model):
    kind: Literal["insight", "text"]
    name: str
    description: str = ""
    query: dict[str, Any] | None = None
    text: str | None = None
    layout: GridLayout


class PanelVerdict(_Model):
    key: str
    title: str
    outcome: PanelOutcome
    reason: str = ""
    tile: TileDraft | None = None


class ImportSummary(_Model):
    total: int
    imported: int
    approximated: int
    failed: int
    skipped: int

    @classmethod
    def from_verdicts(cls, verdicts: list[PanelVerdict]) -> ImportSummary:
        def count(outcome: PanelOutcome) -> int:
            return sum(1 for verdict in verdicts if verdict.outcome == outcome)

        return cls(
            total=len(verdicts),
            imported=count("imported"),
            approximated=count("approximated"),
            failed=count("failed"),
            skipped=count("skipped"),
        )


class ImportResult(_Model):
    status: Literal["completed", "failed"]
    dashboard_id: int | None = None
    error: str | None = None
    summary: ImportSummary
    panels: list[PanelVerdict]


class ImportState(_Model):
    """The value the import keeps under its key in the task state."""

    source: ImportSource
    user_id: int
    dashboard_name: str
    date_from: str | None = None
    promql_available: bool
    spec: DashboardSpec | None = None
    resolved: list[PanelVerdict] = Field(default_factory=list)
    input_paths: list[str] = Field(default_factory=list)
    started_at: str
    finalizing_since: str | None = None
    result: ImportResult | None = None
