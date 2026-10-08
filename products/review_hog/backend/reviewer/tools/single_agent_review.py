"""The single-agent Flash review: one Codex session reviews the whole PR from one prompt.

The prompt has three parts. `core.md` is the DevEx-owned review rubric and goes in as the system
prompt. `prompt.jinja` carries the PR (title, description, numbered diff), the findings of earlier
turns, and the finding format. `schema.json` is generated from
`SingleAgentReview`. All three live in `prompts/single_agent_review/`, so a prompt iteration edits
files and no code.
"""

import re
import json

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.constants import (
    SINGLE_AGENT_CHUNK_ID,
    SINGLE_AGENT_PASS_NUMBER,
    SINGLE_AGENT_SOURCE,
)
from products.review_hog.backend.reviewer.models import PROMPTS_DIR
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.single_agent_review import SingleAgentReview
from products.review_hog.backend.reviewer.tools.prompt_helpers import load_template_and_schema

SINGLE_AGENT_PROMPT_DIR = "single_agent_review"
SINGLE_AGENT_CORE_FILE = PROMPTS_DIR / SINGLE_AGENT_PROMPT_DIR / "core.md"

# The leading HTML comment of core.md holds attribution for maintainers, not instructions.
_LEADING_HTML_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.S)

_STORED_PRIORITY = {
    "P0": IssuePriority.MUST_FIX,
    "P1": IssuePriority.MUST_FIX,
    "P2": IssuePriority.SHOULD_FIX,
    "P3": IssuePriority.CONSIDER,
}


def load_core_prompt() -> str:
    """The core rubric as the model receives it."""
    return _LEADING_HTML_COMMENT.sub("", SINGLE_AGENT_CORE_FILE.read_text(), count=1).strip()


class SingleAgentPrompt:
    """The task prompt of one single-agent review: the PR, earlier findings, format."""

    def __init__(
        self,
        *,
        repository: str,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        prior_findings: list[ReviewIssueFinding],
    ) -> None:
        self.repository = repository
        self.pr_metadata = pr_metadata
        self.pr_files = pr_files
        self.prior_findings = prior_findings

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

    def _diff(self) -> str:
        sections = []
        for pr_file in self.pr_files:
            body = self._numbered_lines(pr_file) or ["(no patch available, the file is binary or too large)"]
            sections.append("\n".join([f"=== {pr_file.filename} [{pr_file.status}] ===", *body]))
        return "\n\n".join(sections)

    def _file_list(self) -> str:
        return "\n".join(f"- {f.filename} ({f.status}, +{f.additions} -{f.deletions})" for f in self.pr_files)

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

    def render(self) -> str:
        template, output_schema = load_template_and_schema(SINGLE_AGENT_PROMPT_DIR)
        return template.render(
            PR_NUMBER=self.pr_metadata.number,
            REPOSITORY=self.repository,
            HEAD_SHA=self.pr_metadata.head_sha or self.pr_metadata.head_branch,
            PR_TITLE=self.pr_metadata.title,
            PR_DESCRIPTION=self.pr_metadata.body.strip() or "(no description provided)",
            FILE_LIST=self._file_list(),
            DIFF=self._diff(),
            COVERED_FINDINGS=self._covered_findings(),
            OUTPUT_SCHEMA=output_schema,
        )


def issues_from_review(review: SingleAgentReview) -> list[Issue]:
    """Map the single agent's findings onto the pipeline's `Issue`, which dedup and publish consume."""
    issues = []
    for number, finding in enumerate(review.findings, start=1):
        line_end = finding.line_end if finding.line_end is not None and finding.line_end != finding.line_start else None
        issues.append(
            Issue(
                id=f"{SINGLE_AGENT_PASS_NUMBER}-{SINGLE_AGENT_CHUNK_ID}-{number}",
                title=finding.title,
                file=finding.file,
                lines=[LineRange(start=finding.line_start, end=line_end)],
                issue=finding.body,
                # The body ends with the fix direction, so there is no separate suggestion text.
                suggestion="",
                suggestion_code=finding.suggestion_code or None,
                priority=_STORED_PRIORITY[finding.priority],
                is_directly_related_to_changes=True,
                source_perspective=SINGLE_AGENT_SOURCE,
            )
        )
    return issues
