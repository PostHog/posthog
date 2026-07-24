"""The arbiter behind the line-proximity gate: did the post-review diff actually fix the finding?

A commit touching a finding's lines is necessary but not sufficient — it could be an unrelated edit,
a formatting sweep, or a change that made the finding worse. This one-shot LLM call reads the finding
and the diff that touched it and rules addressed / not. It runs on `OUTCOME_JUDGE_MODEL`, a different
model family than the reviewer, so it doesn't inherit the blind spots the telemetry exists to measure.
"""

from pydantic import BaseModel, Field

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import OUTCOME_JUDGE_MODEL, OUTCOME_JUDGE_REASONING_EFFORT
from products.review_hog.backend.reviewer.sandbox.direct_llm import run_oneshot_review

_SYSTEM_PROMPT = (
    "You judge whether a code change addressed a specific code-review finding. You are given the "
    "finding (what a reviewer flagged) and the diff that landed on the pull request after the review "
    "was posted. Decide whether that diff actually resolves the finding — not merely touches the same "
    "lines. Formatting-only edits, unrelated refactors, and changes that leave the flagged problem in "
    "place are NOT addressed. Be strict: when the diff does not clearly resolve the finding, answer "
    "addressed=false."
)


class OutcomeJudgeVerdict(BaseModel):
    """The judge's ruling on whether the post-review diff resolved the finding."""

    addressed: bool = Field(description="True only if the diff clearly resolves the finding.")
    reasoning: str = Field(description="One or two sentences on why the diff does or doesn't resolve it.")


def _build_prompt(*, finding: ReviewIssueFinding, verdict: ValidationVerdict, touching_diff: str) -> str:
    line_refs = ", ".join(
        f"L{lr.start}" if lr.end is None or lr.end == lr.start else f"L{lr.start}-{lr.end}" for lr in finding.lines
    )
    return (
        f"<finding>\n"
        f"File: {finding.file}\n"
        f"Lines: {line_refs or 'n/a'}\n"
        f"Title: {finding.title}\n"
        f"Problem: {finding.body}\n"
        f"Suggested fix: {finding.suggestion}\n"
        f"Why it's valid: {verdict.argumentation}\n"
        f"</finding>\n\n"
        f"<diff_landed_after_review>\n{touching_diff}\n</diff_landed_after_review>\n\n"
        f"Did this diff resolve the finding?"
    )


async def judge_addressed(
    *,
    team_id: int,
    user_id: int,
    finding: ReviewIssueFinding,
    verdict: ValidationVerdict,
    touching_diff: str,
) -> bool:
    """Whether the diff that landed after review resolved ``finding``. Raises for the Temporal retry."""
    result = await run_oneshot_review(
        team_id=team_id,
        user_id=user_id,
        prompt=_build_prompt(finding=finding, verdict=verdict, touching_diff=touching_diff),
        system_prompt=_SYSTEM_PROMPT,
        model_to_validate=OutcomeJudgeVerdict,
        step_name="outcome_judge",
        model=OUTCOME_JUDGE_MODEL,
        reasoning_effort=OUTCOME_JUDGE_REASONING_EFFORT,
    )
    return result.addressed
