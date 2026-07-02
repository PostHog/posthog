from typing import Literal

from pydantic import BaseModel, Field


class BriefSectionOut(BaseModel):
    kind: str = Field(description="Section kind, e.g. 'what_happened' or 'what_to_build_next'.")
    title: str = Field(description="Short, specific section heading.")
    markdown: str = Field(description="Section body in markdown. Only reference numbers present in the input.")
    citations: list[str] = Field(description="Evidence refs from the input, verbatim, e.g. 'insight:abc123'.")
    confidence: float = Field(description="Honest confidence in this section, 0.0-1.0.")


class OpportunityOut(BaseModel):
    kind: Literal["build", "fix", "instrument"] = Field(
        description="build = product opportunity, fix = broken PostHog resource, instrument = missing tracking."
    )
    title: str = Field(description="Short, actionable opportunity title.")
    summary: str = Field(description="What was observed and why it matters, grounded in the input numbers.")
    suggested_action: str = Field(description="The concrete next step a product team should take.")
    evidence_refs: list[str] = Field(description="Evidence refs from the input, verbatim.")
    fingerprint_hint: str = Field(description="The fingerprint_hint of the source item, copied through unchanged.")
    confidence: float = Field(description="Honest confidence in this opportunity, 0.0-1.0.")


class BriefOut(BaseModel):
    sections: list[BriefSectionOut] = Field(description="Brief sections, most important first.")
    opportunities: list[OpportunityOut] = Field(description="Ranked opportunities, at most 3.")
