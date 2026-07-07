import json

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import Issue
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk
from products.review_hog.backend.reviewer.tools.prompt_helpers import (
    build_chunk_prompt_context,
    load_template_and_schema,
)


def _covered_findings_for_chunk(
    prior_findings: list[ReviewIssueFinding],
    same_turn_findings: list[Issue],
    chunk: Chunk,
) -> str | None:
    """The already-covered findings on this chunk's files, as compact JSON — or None if there are none.

    Merges cross-turn `prior_findings` (from earlier turns of this PR) with `same_turn_findings` (issues
    the perspective wave already raised on this chunk THIS turn — populated only for the blind-spot
    check). Only file/lines/title/problem are surfaced (not our suggestion): the agent needs to
    recognize the problem as already raised, not re-derive our fix.
    """
    chunk_files = {f.filename for f in chunk.files}
    covered: list[dict[str, object]] = [
        {"file": f.file, "lines": [lr.model_dump(mode="json") for lr in f.lines], "title": f.title, "problem": f.body}
        for f in prior_findings
        if f.file in chunk_files
    ]
    covered += [
        {"file": i.file, "lines": [lr.model_dump(mode="json") for lr in i.lines], "title": i.title, "problem": i.issue}
        for i in same_turn_findings
        if i.file in chunk_files
    ]
    return json.dumps(covered, indent=2) if covered else None


def _format_wave_perspectives(wave_perspectives: dict[str, str]) -> str:
    """The wave's lenses as a markdown list for the blind-spot check's prompt."""
    return "\n".join(f"- `{name}` — {description}" for name, description in wave_perspectives.items())


REVIEW_SYSTEM_PROMPT = (
    "You are a senior code reviewer focused on identifying and documenting issues in a GitHub PR chunk.\n"
    "Focus on:\n"
    "- Identifying real issues that impact code quality, security, or performance\n"
    "- Providing specific, actionable suggestions for each issue\n"
    "- Categorizing issues by priority (must_fix, should_fix, consider)\n"
    "- Following the specific output format requirements for IssuesReview\n"
    "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
)


def build_review_prompt(
    *,
    skill_name: str,
    skill_version: int,
    chunk: Chunk,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    prior_findings: list[ReviewIssueFinding],
    same_turn_findings: list[Issue] | None = None,
    dig_deeper: bool = False,
    blind_spot_check: bool = False,
    wave_perspectives: dict[str, str] | None = None,
) -> str:
    """Render one (perspective, chunk) review prompt — also the blind-spot check's, via the same shape.

    Each (perspective × chunk) review is independent — no cross-perspective context; overlap between
    perspectives is resolved downstream by deduplication. The reviewer reconstructs the chunk's intent
    itself from the diff + `<pr_intent>` (its mandated investigation step), so no separate analysis
    pass is fed in. The skill's focus isn't spliced in — the prompt instructs the agent to `skill-get`
    it over MCP — so we pass the skill name and pinned version, not its body. `prior_findings` are
    problems earlier turns already found on this chunk's files; surfacing them tells the agent not to
    re-investigate already-covered ground.

    The blind-spot check adds cross-perspective context WITHIN a turn: `same_turn_findings` are issues
    the wave already raised on this chunk this turn; `dig_deeper` reframes the covered block as "go
    beyond these"; `wave_perspectives` (skill name → description) tells the agent which lenses ran on
    this chunk, so its `skill-get`-loaded sweep knows what ground is spoken for. `blind_spot_check` is
    an explicit flag (not inferred from `wave_perspectives`) because perspective selection can leave a
    chunk with NO lenses — the sweep must then be told it is the chunk's only reviewer.
    """
    main_template, output_schema = load_template_and_schema("issues_review")
    return main_template.render(
        **build_chunk_prompt_context(chunk, pr_metadata, pr_comments, pr_files),
        COVERED_FINDINGS=_covered_findings_for_chunk(prior_findings, same_turn_findings or [], chunk),
        DIG_DEEPER=dig_deeper,
        IS_BLIND_SPOT=blind_spot_check,
        WAVE_PERSPECTIVES=_format_wave_perspectives(wave_perspectives) if wave_perspectives else None,
        OUTPUT_SCHEMA=output_schema,
        PERSPECTIVE_SKILL_NAME=skill_name,
        PERSPECTIVE_SKILL_VERSION=skill_version,
    )
