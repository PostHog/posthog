"""The shapes that suggested dashboards store, and the answers that the AI steps return.

A template panel holds a finished insight query, the same JSON that an insight saves. So a dashboard that a
person changed, by hand or with PostHog AI, goes back into the template without loss. The AI steps answer in
the smaller builder shape of the dashboard import, and PostHog checks and converts each answer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from products.metrics.backend.dashboard_import.spec import BuilderQuery, DisplaySpec, GridLayout

MAX_REASON_LENGTH = 120


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TemplatePanel(_Model):
    key: str
    title: str
    description: str = ""
    # A MetricsQuery or MetricsHistogramQuery insight query. A text panel has none.
    query: dict[str, Any] | None = None
    text: str | None = None
    layout: GridLayout


class TemplateDefinition(_Model):
    """A curated template file in the bank directory."""

    name: str
    description: str
    panels: list[TemplatePanel]


# The AI answers. Field descriptions are part of the prompt, so they stay short and exact.


class SuggestedTemplateAnswer(_Model):
    key: str = Field(description="The key of one candidate dashboard.")
    reason: str = Field(
        description="A short phrase for the user that says what the dashboard shows from their metrics, in sentence "
        "case with no final period. At most 50 characters. Example: 'Cluster traffic, errors and latency'."
    )


class ProposedDashboardAnswer(_Model):
    name: str = Field(
        description="A short name after the technology or the domain, for example 'Checkout service' or 'Job queue'. "
        "Never a company, customer or person name."
    )
    description: str = Field(description="One sentence that says what the dashboard shows. At most 120 characters.")
    metric_names: list[str] = Field(description="The exact metric names from the catalog that the dashboard uses.")


class EvaluationAnswer(_Model):
    suggested: list[SuggestedTemplateAnswer] = Field(
        description="The candidate dashboards that suit this project. Empty when none fits."
    )
    new_dashboards: list[ProposedDashboardAnswer] = Field(
        description="At most five new dashboards for related metrics that no suggested dashboard covers. Empty when "
        "no such group exists."
    )


class DraftPanel(_Model):
    key: str = Field(description="p1, p2, p3 and so on, in reading order.")
    title: str = Field(description="A short title in sentence case. At most 40 characters.")
    query: BuilderQuery
    display: DisplaySpec
    layout: GridLayout


class DashboardDraft(_Model):
    name: str = Field(description="A short dashboard name in sentence case.")
    description: str = Field(description="One sentence that says what the dashboard shows. At most 120 characters.")
    panels: list[DraftPanel]


class PreviewCritique(_Model):
    looks_good: bool = Field(
        description="True when a person could use the dashboard as it is: every panel shows data, every chart type "
        "and unit fits its metric, and the layout has no holes or overlaps."
    )
    problems: list[str] = Field(
        description="Each problem in one short sentence. Empty when looks_good is true.",
    )
    panels: list[DraftPanel] = Field(
        description="The complete corrected panel list when looks_good is false. Empty when looks_good is true."
    )


class GenerationRound(_Model):
    round: int
    asset_id: int | None = None
    looks_good: bool | None = None
    problems: list[str] = Field(default_factory=list)
    # True when the model corrected the panels after this round, so its problems are fixed in the next one.
    revised: bool = False


class GenerationRecord(_Model):
    """The `generation` value of a generated template."""

    model: str = ""
    requested_name: str = ""
    rounds: list[GenerationRound] = Field(default_factory=list)
    # The panels in the shape that the model writes, so that a check round can show the model its own panels.
    draft_panels: list[DraftPanel] = Field(default_factory=list)
    attributes: dict[str, list[str]] = Field(default_factory=dict)
    attribute_values: dict[str, list[str]] = Field(default_factory=dict)
    dropped_panels: list[str] = Field(default_factory=list)
    error: str | None = None
