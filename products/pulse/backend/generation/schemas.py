from typing import Literal

from pydantic import BaseModel, Field

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


class OpportunityOut(BaseModel):
    kind: Literal["build", "fix", "instrument"] = Field(description=_KIND_FIELD_DESCRIPTION)
    title: str = Field(description="Short, actionable opportunity title.")
    summary: str = Field(description="What was observed and why it matters.")
    suggested_action: str = Field(description="The concrete next step a product team should take.")
    evidence_refs: list[str] = Field(description="Evidence refs from the input, verbatim.")
    fingerprint_hint: str = Field(description="The fingerprint_hint of the source item, copied through unchanged.")
    confidence: float = Field(description="Confidence in this opportunity, 0.0-1.0.")


class BriefOut(BaseModel):
    sections: list[BriefSectionOut] = Field(description="Brief sections, most important first.")
    opportunities: list[OpportunityOut] = Field(description="Ranked opportunities, best first.")
