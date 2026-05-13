"""Pydantic schemas for the cofounder validation stage.

The LLM is asked to return a `ValidationReport` shape via structured output. Every nested
model uses `Literal` enums where the LLM should pick from a fixed vocabulary so the frontend
can render with confidence (e.g. color a "high" severity risk red).

Field-level `description=` strings double as instructions to the LLM — they show up in the
JSON schema the model sees, so prefer concrete, opinionated wording over generic labels.
"""

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["low", "medium", "high"]
Severity = Literal["low", "medium", "high"]
RiskCategory = Literal["market", "technical", "regulatory", "execution", "timing", "other"]


class IdeationInput(BaseModel):
    """The shape of stage 1 output that validation consumes. Mirrors the JSON column on CofounderProject."""

    what: str = Field(description="The product or service the founder wants to build.")
    how: str = Field(description="How the product works — the mechanism, technology, or delivery model.")
    who: str = Field(description="The target customer or user segment.")
    problem: str = Field(description="The problem this solves and why it matters to the target customer.")


class Competitor(BaseModel):
    name: str = Field(description="The actual company name. Be specific — no generic categories.")
    description: str = Field(description="One sentence on what they do.")
    positioning: str = Field(description="How they go to market — pricing, channel, target segment.")
    pricing: str | None = Field(default=None, description="Rough pricing if publicly known; null otherwise.")
    strengths: list[str] = Field(description="What they do well (max 3 bullets).")
    weaknesses: list[str] = Field(description="Where they fall short (max 3 bullets).")
    source_url: str | None = Field(
        default=None,
        description=(
            "Primary URL cited in the research findings for this competitor (homepage, pricing page, or press article). "
            "Null if no source was cited. Must be one of the URLs that appeared in the research findings — do not invent URLs."
        ),
    )


class Differentiation(BaseModel):
    summary: str = Field(description='One-line "we are X for Y" positioning vs the competitive landscape.')
    moat: str = Field(description='What makes this defensible long-term. If unclear, return "unclear" and explain why.')
    gap_in_market: str = Field(description="The specific gap existing players miss that this idea fills.")


class Assumption(BaseModel):
    statement: str = Field(description="A single testable assumption that must be true for the idea to work.")
    risk_if_false: str = Field(description="What breaks if this assumption is wrong.")
    current_confidence: Confidence = Field(
        description="Honest assessment of how much evidence currently supports this assumption."
    )


class ValidationExperiment(BaseModel):
    assumption_index: int = Field(description="Zero-indexed position of the assumption this experiment tests.")
    name: str = Field(description="Short label for the experiment (3-6 words).")
    description: str = Field(description="Concrete steps the founder runs. Should be actionable today.")
    cost_estimate: str = Field(description='Cost in dollars and time, e.g. "$0, 2 hours" or "$200, 1 week".')
    success_signal: str = Field(description="What outcome would tell the founder the assumption holds.")


class Risk(BaseModel):
    category: RiskCategory = Field(description="Which dimension this risk lives in.")
    description: str = Field(description="Specific risk — not generic. Name the actual failure mode.")
    severity: Severity = Field(description="How damaging if it materializes.")


class Verdict(BaseModel):
    score: int = Field(ge=1, le=10, description="Overall 1-10 score weighing market, defensibility, and feasibility.")
    confidence: Confidence = Field(description="How confident in this score given the information provided.")
    reasoning: str = Field(description="One short paragraph explaining the score. Honest, not flattering.")
    next_steps: list[str] = Field(
        description="Three to five concrete actions the founder should take next, ordered by priority."
    )


class ValidationReport(BaseModel):
    """The full structured output the LLM produces. Stored as JSON on ValidationReport.report."""

    competitors: list[Competitor] = Field(description="Three to six real competitors, direct and indirect.")
    differentiation: Differentiation
    assumptions: list[Assumption] = Field(
        description="Three to five critical assumptions ordered by riskiness, riskiest first."
    )
    experiments: list[ValidationExperiment] = Field(
        description="One concrete validation experiment per assumption, indexed by assumption_index."
    )
    risks: list[Risk] = Field(description="Three to six top risks across the listed categories.")
    verdict: Verdict
