"""Pydantic mirror of the frontend `ChartSpec` (frontend/src/lib/components/ChartSpecRenderer/chartSpec.ts).

Prototype only: in production this type should be authored in the assistant TypeScript schema and
codegen'd into `posthog/schema.py` via `pnpm schema:build`, so the LLM contract, the Pydantic
validator, and the React renderer all derive from one source. It is hand-written here to prove the
generation half in isolation without running the (heavy) schema build.

Field descriptions matter — they are dereferenced into the JSON schema the model fills in.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChartType = Literal["line", "bar", "combo", "timeSeriesLine", "pie", "metricCard"]
ValueFormat = Literal["numeric", "short", "percentage", "percentage_scaled", "currency", "duration", "duration_ms"]
AxisId = Literal["left", "right"]


class ChartSpecAxis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: AxisId = Field(description="Which side this axis is on. Series target it via `axis`.")
    label: str | None = Field(default=None, description="Axis title shown beside the axis.")
    format: ValueFormat | None = Field(default=None, description="Numeric formatting for ticks on this axis.")
    currency: str | None = Field(default=None, description="ISO currency code (e.g. 'USD') when format is 'currency'.")
    scale: Literal["linear", "log"] | None = Field(default=None, description="Scale type. Defaults to 'linear'.")
    startAtZero: bool | None = Field(
        default=None, description="Clamp the baseline to zero (default true). False floats to the data range."
    )


class ChartSpecSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Stable unique identifier for the series.")
    label: str = Field(description="Human-readable name shown in legend and tooltip.")
    data: list[float] = Field(description="One value per x-axis label. Must match `labels` length.")
    color: str | None = Field(default=None, description="CSS color. Omit to auto-assign from the brand palette.")
    type: Literal["line", "bar", "area"] | None = Field(
        default=None, description="Combo charts only: how to draw this series."
    )
    axis: AxisId | None = Field(default=None, description="Which axis to scale against. Defaults to 'left'.")
    fill: bool | None = Field(default=None, description="Fill the area under a line (line charts).")
    dashed: bool | None = Field(default=None, description="Dash the line — handy for forecasts or targets.")


class ChartSpecReferenceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | str = Field(description="A numeric value (horizontal line) or an x-axis label (vertical marker).")
    orientation: Literal["horizontal", "vertical"] | None = Field(default=None, description="Defaults to 'horizontal'.")
    label: str | None = Field(default=None, description="Text label drawn on the line.")
    variant: Literal["goal", "alert", "marker"] | None = Field(
        default=None, description="Style: 'goal' (dashed grey), 'alert' (dashed red), 'marker' (solid thin)."
    )
    axis: AxisId | None = Field(default=None, description="Which axis a horizontal line is measured against.")


class ChartSpecConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stacked: bool | None = Field(default=None, description="Stack series (bar/area).")
    grouped: bool | None = Field(default=None, description="Group bars side by side instead of stacking.")
    percent: bool | None = Field(default=None, description="Normalize the stack to 100%.")
    horizontal: bool | None = Field(default=None, description="Bar charts only: horizontal (ranked list) layout.")
    donut: bool | None = Field(default=None, description="Pie charts only: render as a donut.")
    showLegend: bool | None = Field(default=None, description="Show an interactive legend.")
    showGrid: bool | None = Field(default=None, description="Show horizontal grid lines.")
    showValueLabels: bool | None = Field(default=None, description="Draw each point/bar value on the chart.")


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chartType: ChartType = Field(
        description="Chart family. 'combo' mixes bars and lines, 'timeSeriesLine' for ISO-date x labels, "
        "'metricCard' for a single headline number with a sparkline."
    )
    title: str | None = Field(default=None, description="Short chart title.")
    narrative: str | None = Field(
        default=None, description="One sentence on what this chart shows and why — surfaced to the user."
    )
    labels: list[str] = Field(
        description="X-axis labels (ISO date strings for 'timeSeriesLine'). Same length as each series `data`."
    )
    series: list[ChartSpecSeries] = Field(description="The series to plot (at least one).")
    axes: list[ChartSpecAxis] | None = Field(default=None, description="Axis definitions. Two for a dual-axis chart.")
    config: ChartSpecConfig | None = Field(default=None, description="Layout and decoration toggles.")
    referenceLines: list[ChartSpecReferenceLine] | None = Field(
        default=None, description="Goal lines and event markers."
    )
