"""The single-agent Flash review: a main Codex session reviews the whole PR, and lens sessions add breadth.

The main session's prompt has three parts. `core.md` is the DevEx-owned review rubric and goes in as
the system prompt. `prompt.jinja` carries the PR (title, description, numbered diff), the findings of
earlier turns, and the finding format. `schema.json` is generated from `SingleAgentReview`. A lens
session swaps `core.md` for its lens prompt (`FLASH_LENSES`), can see only its part of the PR, and
gets `lens_priority.md` after the finding format. Every file lives in `prompts/single_agent_review/`,
so a prompt iteration edits files and no code.
"""

import re
import json
import asyncio
import logging
from collections import Counter
from dataclasses import replace
from pathlib import Path

from posthog.dataclasses import frozen

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import (
    FLASH_LENSES,
    FLASH_MUST_FIX_CAP_MULTIPLIER,
    FLASH_PROMPT_DIFF_MAX_CHARS,
    SINGLE_AGENT_SOURCE,
    flash_max_findings,
    priority_rank,
)
from products.review_hog.backend.reviewer.models import PROMPTS_DIR
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import (
    DropDisposition,
    DroppedIssue,
    Issue,
    IssuePriority,
    LineRange,
)
from products.review_hog.backend.reviewer.models.single_agent_review import SingleAgentReview
from products.review_hog.backend.reviewer.tools.issue_deduplicator import DedupOutcome, Duplicate, deduplicate_issues
from products.review_hog.backend.reviewer.tools.prompt_helpers import load_template_and_schema
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import is_reviewable_path

logger = logging.getLogger(__name__)

SINGLE_AGENT_PROMPT_DIR = "single_agent_review"
SINGLE_AGENT_PROMPT_PATH = PROMPTS_DIR / SINGLE_AGENT_PROMPT_DIR
SINGLE_AGENT_CORE_FILE = SINGLE_AGENT_PROMPT_PATH / "core.md"
LENS_PRIORITY_FILE = SINGLE_AGENT_PROMPT_PATH / "lens_priority.md"

# The leading HTML comment of a prompt file holds attribution for maintainers, not instructions.
_LEADING_HTML_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.S)

# A full SHA-1 or SHA-256 commit id. The prompt puts the merge base into a shell command the session
# runs, so only a value of this shape may reach it.
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

_STORED_PRIORITY = {
    "P0": IssuePriority.MUST_FIX,
    "P1": IssuePriority.MUST_FIX,
    "P2": IssuePriority.SHOULD_FIX,
    "P3": IssuePriority.CONSIDER,
}


def load_prompt_file(path: Path) -> str:
    """A prompt file as the model receives it."""
    return _LEADING_HTML_COMMENT.sub("", path.read_text(), count=1).strip()


def lens_prompt_path(prompt_file: str) -> Path:
    return SINGLE_AGENT_PROMPT_PATH / prompt_file


def load_core_prompt() -> str:
    """The core rubric as the model receives it."""
    return load_prompt_file(SINGLE_AGENT_CORE_FILE)


class SingleAgentPrompt:
    """The task prompt of one single-agent session: the PR or its part, earlier findings, format.

    `scope_files` limits the diff to one lens part. A diff over `FLASH_PROMPT_DIFF_MAX_CHARS` shrinks
    to the reviewable files, and then to none: the file list marks each file it leaves out, and the
    session reads those changes with git against `merge_base_sha`.
    """

    def __init__(
        self,
        *,
        repository: str,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        prior_findings: list[ReviewIssueFinding],
        merge_base_sha: str | None = None,
        scope_files: list[str] | None = None,
        for_lens: bool = False,
    ) -> None:
        self.repository = repository
        self.pr_metadata = pr_metadata
        self.merge_base_sha = merge_base_sha
        self.pr_files = pr_files
        self.prior_findings = prior_findings
        self.scope_files = scope_files
        self.for_lens = for_lens

    @staticmethod
    def _numbered_lines(pr_file: PRFile) -> list[str]:
        """The file's changes, each line prefixed with its marker and its line number at the head."""
        lines: list[str] = []
        next_line: int | None = None
        for change in pr_file.changes:
            start = change.new_start_line
            if start is not None and next_line is not None and start != next_line:
                lines.append("...")
            code_lines = change.code.split("\n")
            for offset, code in enumerate(code_lines):
                if change.type == "deletion" or start is None:
                    lines.append(f"-{'':>6} {code}")
                else:
                    marker = "+" if change.type == "addition" else " "
                    lines.append(f"{marker}{start + offset:>6} {code}")
            if start is not None and change.type != "deletion":
                next_line = start + len(code_lines)
        return lines

    @classmethod
    def _diff(cls, pr_files: list[PRFile]) -> str:
        sections = []
        for pr_file in pr_files:
            body = cls._numbered_lines(pr_file) or ["(no patch available, the file is binary or too large)"]
            sections.append("\n".join([f"=== {pr_file.filename} [{pr_file.status}] ===", *body]))
        return "\n\n".join(sections)

    def _in_scope(self) -> list[PRFile]:
        if self.scope_files is None:
            return self.pr_files
        scope = set(self.scope_files)
        return [f for f in self.pr_files if f.filename in scope]

    def _shown_files(self, in_scope: list[PRFile]) -> list[PRFile]:
        """The in-scope files whose diff fits in the prompt: all of them, else the reviewable ones, else none."""
        reviewable = [f for f in in_scope if is_reviewable_path(f.filename)]
        for candidate in (in_scope, reviewable):
            if len(self._diff(candidate)) <= FLASH_PROMPT_DIFF_MAX_CHARS:
                return candidate
        return []

    def _file_list(self, not_shown: set[str]) -> str:
        lines = []
        for f in self.pr_files:
            suffix = ", diff not shown" if f.filename in not_shown else ""
            lines.append(f"- {f.filename} ({f.status}, +{f.additions} -{f.deletions}{suffix})")
        return "\n".join(lines)

    def _covered_findings(self) -> str | None:
        """Earlier turns' findings, without their fixes: the agent only needs to recognize them."""
        covered = [
            {
                "file": f.file,
                "lines": [lr.model_dump(mode="json") for lr in f.lines],
                "title": f.title,
                "problem": f.body,
            }
            for f in self.prior_findings
        ]
        return json.dumps(covered, indent=2) if covered else None

    def _base_sha(self) -> str | None:
        """The merge base when it is a commit id, else None: the prompt then gives no git command."""
        sha = self.merge_base_sha
        return sha if sha is not None and _COMMIT_SHA.fullmatch(sha) else None

    def render(self) -> str:
        template, output_schema = load_template_and_schema(SINGLE_AGENT_PROMPT_DIR)
        in_scope = self._in_scope()
        shown = self._shown_files(in_scope)
        not_shown = {f.filename for f in in_scope} - {f.filename for f in shown}
        # A part that covers the whole PR needs no scope section, because no other session reviews its files.
        scope = [f.filename for f in in_scope] if len(in_scope) < len(self.pr_files) else None
        return template.render(
            PR_NUMBER=self.pr_metadata.number,
            REPOSITORY=self.repository,
            HEAD_SHA=self.pr_metadata.head_sha or self.pr_metadata.head_branch,
            BASE_SHA=self._base_sha(),
            PR_TITLE=self.pr_metadata.title,
            PR_DESCRIPTION=self.pr_metadata.body.strip() or "(no description provided)",
            FILE_LIST=self._file_list(not_shown),
            SCOPE=", ".join(f"`{path}`" for path in scope) if scope else None,
            DIFF=self._diff(shown),
            DIFF_NOT_SHOWN=bool(not_shown),
            COVERED_FINDINGS=self._covered_findings(),
            OUTPUT_SCHEMA=output_schema,
            LENS_PRIORITY=load_prompt_file(LENS_PRIORITY_FILE) if self.for_lens else None,
        )


def issues_from_review(review: SingleAgentReview, *, pass_number: int, chunk_id: int, source: str) -> list[Issue]:
    """Map one session's findings onto the pipeline's `Issue`, which dedup and publish consume.

    Findings go highest priority first. Storage folds P0 and P1 into `must_fix`, so this order is the
    only place a P0 still ranks above a P1 of the same session. `reported_priority` keeps the P level
    for later analysis.
    """
    issues = []
    ranked = sorted(review.findings, key=lambda finding: finding.priority)
    for number, finding in enumerate(ranked, start=1):
        line_end = finding.line_end if finding.line_end is not None and finding.line_end != finding.line_start else None
        issues.append(
            Issue(
                id=f"{pass_number}-{chunk_id}-{number}",
                title=finding.title,
                file=finding.file,
                lines=[LineRange(start=finding.line_start, end=line_end)],
                issue=finding.body,
                # The body ends with the fix direction, so there is no separate suggestion text.
                suggestion="",
                suggestion_code=finding.suggestion_code or None,
                priority=_STORED_PRIORITY[finding.priority],
                reported_priority=finding.priority,
                is_directly_related_to_changes=True,
                source_perspective=source,
            )
        )
    return issues


@frozen
class FlashSelection:
    """The findings a single-agent turn keeps, and every finding it drops with the reason."""

    kept: list[Issue]
    dropped: list[DroppedIssue]
    # The turn's finding cap, which must-fix findings can exceed, and the lens part count it grew with.
    cap: int
    lens_part_count: int
    # A dedup call failed and fell back to the positional pre-filter alone.
    dedup_fell_back: bool = False


def _flash_order(main: list[Issue], lens: list[Issue]) -> list[Issue]:
    """Highest priority first, then the main findings before the lens findings, then the order of the sessions."""
    return sorted([*main, *lens], key=lambda issue: priority_rank(issue.priority), reverse=True)


def compose_flash_findings(main: list[Issue], lens: list[Issue], *, lens_part_count: int) -> FlashSelection:
    """The findings a Flash turn keeps, highest priority first and the main review first on ties.

    Every must-fix (P0 or P1) finding is kept outside the cap (`flash_max_findings`), up to
    `FLASH_MUST_FIX_CAP_MULTIPLIER` times the cap. P2 and then P3 findings fill the slots the must-fix
    findings leave under the cap. The rest drop with their rank.

    The caller persists only the kept findings. A persisted finding that never posts counts as already
    raised, so every later turn would keep it off the PR too.
    """
    cap = flash_max_findings(lens_part_count)
    ranked = _flash_order(main, lens)
    must_fix = [issue for issue in ranked if issue.priority == IssuePriority.MUST_FIX]
    must_fix = must_fix[: FLASH_MUST_FIX_CAP_MULTIPLIER * cap]
    others = [issue for issue in ranked if issue.priority != IssuePriority.MUST_FIX]
    kept_ids = {issue.id for issue in [*must_fix, *others[: max(cap - len(must_fix), 0)]]}
    return FlashSelection(
        kept=[issue for issue in ranked if issue.id in kept_ids],
        dropped=[
            DroppedIssue(issue=issue, disposition="cap", rank=rank)
            for rank, issue in enumerate(ranked, start=1)
            if issue.id not in kept_ids
        ],
        cap=cap,
        lens_part_count=lens_part_count,
    )


# How the completed event names each session: `main`, or the lens name in snake case.
_SESSION_NAMES = {
    SINGLE_AGENT_SOURCE: "main",
    **{lens.source: name.replace("-", "_") for name, lens in FLASH_LENSES.items()},
}


@frozen
class FlashTurnStats:
    """A single-agent turn's findings from dedup to the cap, for the completed event."""

    cap: int
    lens_part_count: int
    reviewable_lines: int
    # Per session: the findings that entered dedup, and how many of them the session itself rated P0/P1.
    candidates: dict[str, int]
    must_fix: dict[str, int]
    after_dedup: int
    # Per disposition: the findings dedup and the cap dropped.
    dropped: dict[str, int]
    kept: int
    # A dedup call failed and fell back to the positional pre-filter alone.
    dedup_fell_back: bool


def flash_turn_stats(candidates: list[Issue], selection: FlashSelection, *, reviewable_lines: int) -> FlashTurnStats:
    """Count a turn's findings per session and per drop reason.

    Must-fix counts read `reported_priority`, because a dedup survivor can be raised above what its
    session reported.
    """
    per_session = dict.fromkeys(_SESSION_NAMES.values(), 0)
    must_fix = dict(per_session)
    for issue in candidates:
        session = _SESSION_NAMES.get(issue.source_perspective or "", issue.source_perspective or "unknown")
        per_session[session] = per_session.get(session, 0) + 1
        if issue.reported_priority in ("P0", "P1"):
            must_fix[session] = must_fix.get(session, 0) + 1
    cut = sum(1 for drop in selection.dropped if drop.disposition == "cap")
    return FlashTurnStats(
        cap=selection.cap,
        lens_part_count=selection.lens_part_count,
        reviewable_lines=reviewable_lines,
        candidates=per_session,
        must_fix=must_fix,
        after_dedup=len(selection.kept) + cut,
        dropped=dict(Counter(drop.disposition for drop in selection.dropped)),
        kept=len(selection.kept),
        dedup_fell_back=selection.dedup_fell_back,
    )


def _dropped_duplicate(
    duplicate: Duplicate,
    *,
    dedup_fallback: bool,
    turn_issues: dict[str, Issue],
    prior_keys: set[str],
) -> DroppedIssue:
    """Record a dedup drop with the survivor it repeats: a finding of this turn, an earlier turn's finding, or a comment."""
    named = duplicate.duplicate_of
    target = turn_issues.get(named) if named is not None else None
    disposition: DropDisposition
    duplicate_of: Issue | str | None = named
    if target is not None:
        repeats_anchor = (
            target.source_perspective == SINGLE_AGENT_SOURCE
            and duplicate.issue.source_perspective != SINGLE_AGENT_SOURCE
        )
        disposition = "dedup_anchor" if repeats_anchor else "dedup_sibling"
        duplicate_of = target
    elif named in prior_keys:
        disposition = "dedup_prior"
    else:
        disposition = "dedup_comment"
        duplicate_of = f"comment:{named}"
    return DroppedIssue(
        issue=duplicate.issue, disposition=disposition, duplicate_of=duplicate_of, dedup_fallback=dedup_fallback
    )


@frozen
class _HeldDuplicate:
    """A dedup removal that holds, pointing at what survives in its place."""

    duplicate: Duplicate
    fell_back: bool


def _resolve_duplicates(
    main: list[Issue],
    lens: list[Issue],
    main_outcome: DedupOutcome,
    lens_outcome: DedupOutcome,
    *,
    earlier_ids: set[str],
) -> list[_HeldDuplicate]:
    """Keep only the removals whose target survives, and point each one at the survivor.

    The dedup can name a finding that it also removes, so two findings that name each other would
    both drop and their problem would leave the review. A finding that names itself, or an id its
    call was not shown, stays. In a loop of findings that name each other, the first one in
    `_flash_order` stays and the others drop into it. A removal whose target drops follows the chain
    to the finding or the earlier coverage (`earlier_ids`: earlier turns' issue keys and PR comment
    ids) that survives.
    """
    main_ids = {issue.id for issue in main}
    lens_ids = {issue.id for issue in lens}
    calls = [
        (main_outcome, main_ids | earlier_ids),
        (lens_outcome, lens_ids | main_ids | earlier_ids),
    ]
    targets: dict[str, str] = {}
    removals: dict[str, _HeldDuplicate] = {}
    for outcome, shown_ids in calls:
        for duplicate in outcome.duplicates:
            issue_id = duplicate.issue.id
            named = duplicate.duplicate_of
            if named is None or named == issue_id or named not in shown_ids:
                logger.warning(
                    "Keeping %s: the dedup named %r, which is not another finding it was shown", issue_id, named
                )
                continue
            targets[issue_id] = named
            removals[issue_id] = _HeldDuplicate(duplicate=duplicate, fell_back=outcome.fell_back)

    rank = {issue.id: position for position, issue in enumerate(_flash_order(main, lens))}
    for start in list(targets):
        path: list[str] = []
        node = start
        while node in targets and node not in path:
            path.append(node)
            node = targets[node]
        if node in path:
            loop = path[path.index(node) :]
            survivor = min(loop, key=rank.__getitem__)
            logger.info("Keeping %s: the dedup removed %s as duplicates of each other", survivor, loop)
            del targets[survivor]

    held = []
    for issue_id, removal in removals.items():
        if issue_id not in targets:
            continue
        survivor = targets[issue_id]
        while survivor in targets:
            survivor = targets[survivor]
        held.append(
            _HeldDuplicate(
                duplicate=Duplicate(issue=removal.duplicate.issue, duplicate_of=survivor),
                fell_back=removal.fell_back,
            )
        )
    return held


def _raise_survivors(kept: list[Issue], duplicates: list[Duplicate]) -> None:
    """Give each kept finding the highest priority among the duplicates dedup removed in its favor.

    Dedup keeps the most complete statement of a problem, not the most severe one, so a lens P1 that
    repeats a main P3 would otherwise post as the P3, or not at all once the cap cuts it.
    """
    kept_by_id = {issue.id: issue for issue in kept}
    for duplicate in duplicates:
        survivor = kept_by_id.get(duplicate.duplicate_of or "")
        if survivor is not None and priority_rank(duplicate.issue.priority) > priority_rank(survivor.priority):
            logger.info(
                "Raising %s to %s: dedup removed %s as its duplicate",
                survivor.id,
                duplicate.issue.priority.value,
                duplicate.issue.id,
            )
            survivor.priority = duplicate.issue.priority


async def dedupe_flash_findings(
    *,
    team_id: int,
    user_id: int,
    issues: list[Issue],
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    prior_findings: list[tuple[ReviewIssueFinding, ValidationVerdict | None]],
    branch: str,
    repository: str,
    lens_part_count: int,
    workflow_id_prefix: str | None = None,
    fall_back_on_any_error: bool = False,
) -> FlashSelection:
    """Deduplicate a single-agent turn's main and lens findings, then keep the few it posts.

    Two dedup calls run in parallel. The main findings dedup against PR comments and earlier turns.
    The lens findings dedup against those too and against the main findings as anchors, so a lens
    finding can lose to a main finding but never the other way around. A removal holds only when what
    it repeats survives (`_resolve_duplicates`). A finding that survives takes the priority of the most
    severe duplicate removed in its favor. `fall_back_on_any_error` lets a dedup
    call fall back to the positional pre-filter on any failure, for the activity's last attempt.
    """
    main = [issue for issue in issues if issue.source_perspective == SINGLE_AGENT_SOURCE]
    lens = [issue for issue in issues if issue.source_perspective != SINGLE_AGENT_SOURCE]
    main_outcome, lens_outcome = await asyncio.gather(
        deduplicate_issues(
            team_id=team_id,
            user_id=user_id,
            issues=main,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            prior_findings=prior_findings,
            branch=branch,
            repository=repository,
            workflow_id_prefix=workflow_id_prefix,
            for_flash=True,
            fall_back_on_any_error=fall_back_on_any_error,
        ),
        deduplicate_issues(
            team_id=team_id,
            user_id=user_id,
            issues=lens,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            prior_findings=prior_findings,
            branch=branch,
            repository=repository,
            workflow_id_prefix=workflow_id_prefix,
            anchors=main,
            for_flash=True,
            fall_back_on_any_error=fall_back_on_any_error,
        ),
    )
    prior_keys = {finding.issue_key for finding, _ in prior_findings}
    comment_ids = {str(comment.id) for comment in pr_comments if comment.id is not None}
    held = _resolve_duplicates(main, lens, main_outcome, lens_outcome, earlier_ids=prior_keys | comment_ids)
    removed_ids = {removal.duplicate.issue.id for removal in held}
    kept_main = [issue for issue in main if issue.id not in removed_ids]
    kept_lens = [issue for issue in lens if issue.id not in removed_ids]
    _raise_survivors([*kept_main, *kept_lens], [removal.duplicate for removal in held])
    composed = compose_flash_findings(kept_main, kept_lens, lens_part_count=lens_part_count)
    turn_issues = {issue.id: issue for issue in issues}
    dedup_drops = [
        _dropped_duplicate(
            removal.duplicate, dedup_fallback=removal.fell_back, turn_issues=turn_issues, prior_keys=prior_keys
        )
        for removal in held
    ]
    logger.info(
        "Flash keeps %s of %s main and %s lens finding(s) left after dedup",
        len(composed.kept),
        len(kept_main),
        len(kept_lens),
    )
    return replace(
        composed,
        dropped=[*dedup_drops, *composed.dropped],
        dedup_fell_back=main_outcome.fell_back or lens_outcome.fell_back,
    )
