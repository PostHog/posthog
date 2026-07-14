from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from products.pulse.backend.models import Opportunity

# Single source of truth for what each opportunity kind means — interpolated into both the
# synthesis prompt and the structured-output field description.
KIND_DESCRIPTIONS: dict[str, str] = {
    Opportunity.Kind.BUILD.value: "a product opportunity",
    Opportunity.Kind.FIX.value: "a broken PostHog resource",
    Opportunity.Kind.INSTRUMENT.value: "missing tracking the team should add",
}
assert set(KIND_DESCRIPTIONS) == set(Opportunity.Kind.values)

_KIND_FIELD_DESCRIPTION = "; ".join(f"{kind} = {description}" for kind, description in KIND_DESCRIPTIONS.items())


class BriefSectionOut(BaseModel):
    kind: str = Field(description="Section kind, e.g. 'what_happened', 'what_to_build_next', or 'accountability'.")
    title: str = Field(description="Short, specific section heading.")
    markdown: str = Field(description="Section body in markdown.")
    citations: list[str] = Field(description="Evidence refs from the input, verbatim, e.g. 'insight:abc123'.")
    confidence: float = Field(description="Confidence in this section, 0.0-1.0.")


class ProposedExperimentOut(BaseModel):
    hypothesis: str = Field(
        max_length=500,
        description="The testable hypothesis, grounded in the opportunity's cited evidence — never in new numbers.",
    )
    flag_key_suggestion: str = Field(
        max_length=200,
        description="A suggested feature flag key for the experiment, kebab-case, e.g. 'sidebar-entry-point'.",
    )
    target_metric_insight_short_id: str = Field(
        max_length=100,
        description=(
            "The short ID of the insight the experiment should move, copied verbatim from a cited insight evidence ref."
        ),
    )
    variant_sketch: str = Field(
        max_length=500,
        description="One or two sentences sketching the control and test variants a team would ship.",
    )


class OpportunityOut(BaseModel):
    kind: Literal["build", "fix", "instrument"] = Field(description=_KIND_FIELD_DESCRIPTION)
    title: str = Field(description="Short, actionable opportunity title.")
    summary: str = Field(description="What was observed and why it matters.")
    suggested_action: str = Field(description="The concrete next step a product team should take.")
    evidence_refs: list[str] = Field(description="Evidence refs from the input, verbatim.")
    fingerprint_hint: str = Field(description="The fingerprint_hint of the source item, copied through unchanged.")
    confidence: float = Field(description="Confidence in this opportunity, 0.0-1.0.")
    goal_relevant: bool = Field(
        default=False,
        description=(
            "True only when this opportunity plausibly advances the stated focus goal and its cited "
            "evidence supports that. Always false when the brief has no goal."
        ),
    )
    proposed_experiment: ProposedExperimentOut | None = Field(
        default=None,
        description=(
            "An experiment worth running for this opportunity. Fill ONLY when goal_relevant is true and "
            "the cited evidence supports the hypothesis; null otherwise. Always null when the brief has "
            "no goal."
        ),
    )


class BriefOut(BaseModel):
    sections: list[BriefSectionOut] = Field(description="Brief sections, most important first.")
    opportunities: list[OpportunityOut] = Field(description="Ranked opportunities, best first.")


class AgentBriefOut(BriefOut):
    """The BriefOut-shaped contract a sandbox agent report must satisfy (see agent/prompt.py).

    Reuses BriefOut's opportunities as-is; it only adds the window echo (validated against the
    pinned mission window) and artifact keys the base brief has no concept of.
    """

    # AwareDatetime (not bare datetime): a naive echo is rejected as a schema violation and funnels
    # through validate_agent_report's ValidationError path, so _check_window never subtracts a naive
    # from an aware DB datetime (USE_TZ=True) and raises an uncaught TypeError.
    window_start: AwareDatetime = Field(description="Start of the frozen window the agent reported on.")
    window_end: AwareDatetime = Field(description="End of the frozen window the agent reported on.")
    artifacts: list[str] = Field(default_factory=list, description="Object-storage keys for agent artifacts.")
