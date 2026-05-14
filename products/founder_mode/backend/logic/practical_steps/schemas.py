"""Pydantic schemas for the practical launch playbook (stage 5b, under the marketing umbrella).

This is the concrete, copy-paste-ready content the founder publishes to promote the MVP.
The conceptual GTM (positioning, pricing, channels) lives in `logic/gtm/` and runs earlier.
"""

from pydantic import BaseModel, ConfigDict, Field

from products.founder_mode.backend.logic.envelope import StageStatus


class SocialPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(description="Platform: 'linkedin', 'twitter', 'reddit', 'indie_hackers', or 'hacker_news'.")
    content: str = Field(description="Full post text, ready to copy-paste and publish.")
    tips: str = Field(description="Timing and format tips for this specific post.")


class PracticalStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="Short title for the action (e.g. 'Hunter outreach for Product Hunt launch').")
    description: str = Field(description="What to do and why it matters.")
    channel: str = Field(description="Where this happens (e.g. 'Product Hunt', 'LinkedIn', 'Twitter/X', 'Reddit').")
    timeline: str = Field(description="When to do this relative to launch day (e.g. 'D-7', 'Launch day', 'D+1').")
    ready_to_use_content: list[SocialPost] = Field(description="Pre-written posts for this step (may be empty).")


class PracticalStepsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_summary: str = Field(description="2-3 sentence overview of the launch strategy.")
    target_communities: list[str] = Field(
        description="Specific communities where the target audience hangs out (e.g. subreddits, Discord servers, Slack groups)."
    )
    steps: list[PracticalStep] = Field(
        description="Ordered list of launch actions, chronological from pre-launch to post-launch."
    )


class MarketingStepsEnvelope(BaseModel):
    """API-facing envelope for the `marketing_steps` JSON column."""

    status: StageStatus | None = Field(
        default=None, description="Lifecycle state of the practical steps generation run."
    )
    result: PracticalStepsResult | None = Field(
        default=None, description="The launch playbook. Present once `status='completed'`."
    )
    started_at: str | None = Field(default=None, description="ISO timestamp when the run kicked off.")
    completed_at: str | None = Field(default=None, description="ISO timestamp when the run finished successfully.")
    failed_at: str | None = Field(default=None, description="ISO timestamp when the run failed.")
    trace_id: str | None = Field(default=None, description="Trace id linking to the underlying LLM calls.")
    error: str = Field(default="", description="Human-readable error message when `status='failed'`. Empty otherwise.")
