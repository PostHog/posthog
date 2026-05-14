"""Pydantic schemas for the conceptual GTM stage (stage 3).

This stage is about positioning, pricing, and high-level acquisition channels — not concrete
launch tactics. The practical launch playbook (Product Hunt copy, LinkedIn posts, etc.) lives
in `logic/practical_steps/` and runs later under the marketing umbrella.
"""

from pydantic import BaseModel, ConfigDict, Field

from products.founder_mode.backend.logic.envelope import StageStatus


class TargetSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Short label for this audience segment (e.g. 'Solo SaaS founders, pre-launch').")
    description: str = Field(
        description="Who they are, where they hang out, what they care about, what signals identify them."
    )
    why_reachable_now: str = Field(
        description="Why this segment is reachable and buyable right now — concrete, time-anchored reasoning."
    )


class PricingTier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Tier name (e.g. Free, Pro, Team, Enterprise).")
    price: str = Field(description="Price point with cadence and currency (e.g. '$29/mo', '$0', 'Contact us').")
    target_segment: str = Field(description="Which TargetSegment this tier is aimed at — reference by name.")
    value: str = Field(description="What the founder is selling at this tier in plain language.")


class GTMSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positioning_statement: str = Field(
        description=(
            "One-paragraph positioning: who it's for, what category, what makes it different. "
            "Should read like a founder-voice deck slide, not marketing copy."
        )
    )
    primary_segment: TargetSegment = Field(
        description="The wedge audience — the single segment the founder should chase first."
    )
    secondary_segments: list[TargetSegment] = Field(
        description="1-3 adjacent segments to expand into once the primary wedge is proven."
    )
    category: str = Field(
        description="Where this plays. New category, existing category, or wedge inside an existing category."
    )
    moat: str = Field(
        description="What makes this defensible over a 12-24 month horizon — be specific, not 'network effects'."
    )
    pricing_philosophy: str = Field(
        description="How this should be priced and why — per-seat vs usage vs flat vs freemium, and the reasoning."
    )
    pricing_tiers: list[PricingTier] = Field(description="2-4 concrete pricing tiers ordered low to high.")
    primary_channel: str = Field(
        description="The single highest-leverage acquisition channel — community, content, paid, partnerships, or sales-led."
    )
    secondary_channels: list[str] = Field(description="2-4 supporting channels in priority order.")


class GTMEnvelope(BaseModel):
    """API-facing envelope for the `gtm` JSON column."""

    status: StageStatus | None = Field(default=None, description="Lifecycle state of the GTM generation run.")
    result: GTMSummary | None = Field(
        default=None, description="The synthesized GTM summary. Present once `status='completed'`."
    )
    started_at: str | None = Field(default=None, description="ISO timestamp when the run kicked off.")
    completed_at: str | None = Field(default=None, description="ISO timestamp when the run finished successfully.")
    failed_at: str | None = Field(default=None, description="ISO timestamp when the run failed.")
    trace_id: str | None = Field(default=None, description="Trace id linking to the underlying LLM calls.")
    error: str = Field(default="", description="Human-readable error message when `status='failed'`. Empty otherwise.")
