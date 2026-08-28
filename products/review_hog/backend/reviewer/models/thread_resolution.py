from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class ThreadOutcome(str, Enum):
    """Terminal outcome of one work-list thread (see CONTEXT.md — "Thread outcome")."""

    FIXED = "fixed"
    WONT_FIX = "wont_fix"
    ALREADY_FIXED = "already_fixed"
    OBSOLETE = "obsolete"
    ESCALATE = "escalate"


class ThreadResolution(BaseModel):
    """One resolution turn's validated output: the verdict on a single review thread.

    The agent judges the thread (worth? safe?), implements + signed-commits when warranted, and
    returns this. GitHub side effects (reply, resolve) are performed by the driver from this
    verdict — the agent never posts comments or resolves threads itself.
    """

    thread_id: str = Field(description="The review thread's node id, echoed back verbatim from the turn's input.")
    outcome: ThreadOutcome = Field(
        description=(
            "fixed: implemented and committed via the signed-commit tooling. "
            "wont_fix: deliberately declined (not worth doing). "
            "already_fixed: the current code already addresses it. "
            "obsolete: superseded by other changes (name them in the reply). "
            "escalate: worth doing but not safe to do unattended — a human must decide."
        )
    )
    reasoning: str = Field(
        description=(
            "Internal assessment for the work log: the worth/safe judgment and what was checked "
            "against the current code, with file:line evidence."
        )
    )
    reply: str = Field(
        description=(
            "The reply to post on the thread: plain, self-contained language a reader can act on "
            "without opening the code — what was done (or why not) and what happens next."
        )
    )
    commit_sha: str | None = Field(
        default=None,
        description=(
            "The pushed commit's SHA exactly as reported by the signed-commit tooling. "
            "Required when outcome is fixed; null otherwise."
        ),
    )
    verification: str | None = Field(
        default=None,
        description="What was run to verify a fix (lint, tests) and the honest result, failures included.",
    )

    @field_validator("thread_id", "reasoning", "reply")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v

    @model_validator(mode="after")
    def fixed_requires_commit(self) -> "ThreadResolution":
        if self.outcome == ThreadOutcome.FIXED and not (self.commit_sha or "").strip():
            raise ValueError("outcome=fixed requires the pushed commit's sha in commit_sha")
        return self
