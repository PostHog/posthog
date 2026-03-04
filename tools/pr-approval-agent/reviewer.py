# ruff: noqa: T201
"""LLM-based PR reviewer using the Claude Agent SDK.

The reviewer uses Read/Grep/Glob/Bash tools to explore the repo
and reach a verdict on whether a PR is safe to auto-approve.
"""

import json
import asyncio
import textwrap
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock
from github import PRData

MODEL = "claude-sonnet-4-6"


def _extract_json(text: str) -> dict:
    """Extract JSON from text that may be wrapped in markdown code blocks."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not parse JSON from LLM output:\n{text[:500]}")


EVIDENCE_JSON_INSTRUCTIONS = textwrap.dedent("""\
    Respond with ONLY a JSON object (no markdown, no code blocks):
    {
        "verdict": "APPROVE" | "REFUSE" | "ESCALATE",
        "reasoning": "1 sentence: your judgment call, not a code summary.",
        "risk": "low" | "medium" | "high",
        "issues": ["concrete concerns if any, empty if none"]
    }

    The "reasoning" will be posted as a GitHub review comment, so write it as
    a short human-readable sentence — why it's safe or why it's not. Do NOT
    describe what the code does. The author already knows.
""")

REVIEWER_SYSTEM = textwrap.dedent(
    """\
    You decide whether a pull request is safe for automated approval.
    Your core question: are there showstoppers that block auto-approval?
    If none, approve. If you find one, refuse or escalate.

    Showstoppers (REFUSE or ESCALATE):
    - Could break production (crashes, data loss, silent corruption)
    - Touches dependencies, data models, or API contracts the gates missed
    - CI/infra changes that slipped through the deny-list
    - Security issues (injection, auth bypass, data exposure)
    - Unaddressed review comments with substantive concerns
    - Bot author (dependabot, renovate) — always needs human review

    NOT showstoppers (just approve):
    - Code style, naming, missing comments, "could be refactored better"
    - Typos, log strings, test fixes, config tweaks
    - Anything purely cosmetic or additive without risk

    Context: Deterministic gates already verified no deny-list matches (auth,
    crypto, migrations, infra/CI, billing, public API, deps), CI is green,
    no outstanding "changes requested". You only see T1 PRs that passed.

    T1 sub-tiers (provided in the prompt):
    - T1a-trivial: ≤20 lines, ≤3 files, single area
    - T1b-small: ≤100 lines, ≤5 files, focused
    - T1c-medium: ≤300 lines, ≤15 files, focused
    - T1d-complex: >300 lines or >15 files
    Calibrate scrutiny to the sub-tier. T1a should be quick.

    Ownership (from CODEOWNERS-soft, non-blocking):
    - Author on owning team: not a concern
    - Author NOT on owning team:
      - Fine: typo fixes, log strings, test fixes, comments, mechanical refactors
      - ESCALATE: behavioral changes to business logic, API contracts, data models

    Review comments (inline feedback only, approval states are hidden):
    - Substantive comments unresolved by the current diff → REFUSE
    - Bot comments with valid concerns that were ignored → ESCALATE

    Tools: You have Read, Grep, Glob, and Bash. All PR metadata (comments,
    ownership) is in the prompt — do NOT fetch from GitHub.
    1. Run the git diff command to see what changed
    2. Read source files only if something looks off
    3. ESCALATE if you'd need deep review to feel confident

    Verdicts:
    - APPROVE: no showstoppers found
    - REFUSE: concrete issue found
    - ESCALATE: not confident, or needs domain expertise
    When in doubt, ESCALATE rather than APPROVE.

    IMPORTANT: The "reasoning" field is 1 sentence — your judgment call, not a
    code review. Do NOT describe what the code does. Examples:
    - "No showstoppers, low-risk frontend fix."
    - "Missing tests for new error handling path."
    - "Touches shared query builder — needs team review."

    """
    + EVIDENCE_JSON_INSTRUCTIONS
)


# ── Reviewer (Agent SDK — explores the repo) ────────────────────


class Reviewer:
    """LLM reviewer using Agent SDK."""

    def __init__(self, repo_root: Path, *, verbose: bool = False):
        self.repo_root = repo_root
        self.verbose = verbose

    def review(self, pr: PRData, classification: dict, gate_context: dict) -> dict:
        """Claude explores the repo and produces a verdict."""
        return asyncio.run(self._review(pr, classification, gate_context))

    # ── Review implementation ────────────────────────────────────

    async def _review(self, pr: PRData, classification: dict, gate_context: dict) -> dict:
        prompt = self._build_review_prompt(pr, classification, gate_context)
        options = ClaudeAgentOptions(
            system_prompt=REVIEWER_SYSTEM,
            allowed_tools=["Read", "Grep", "Glob", "Bash"],
            disallowed_tools=["Write", "Edit", "NotebookEdit"],
            cwd=str(self.repo_root),
            max_turns=20,
            model=MODEL,
            permission_mode="acceptEdits",
        )

        result_text = ""
        async for message in query(prompt=prompt, options=options):
            if self.verbose:
                print(f"\033[2m    [{type(message).__name__}]\033[0m", flush=True)
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock) and self.verbose:
                        self._log_tool_call(block)
                    if isinstance(block, TextBlock):
                        result_text = block.text

        if not result_text.strip():
            raise RuntimeError("Reviewer agent returned no output")
        return _extract_json(result_text)

    def _log_tool_call(self, block: ToolUseBlock) -> None:
        name = block.name
        inp = getattr(block, "input", None) or {}
        if name == "Read":
            path = inp.get("file_path", "?")
            print(f"\033[2m    Read {path}\033[0m", flush=True)
        elif name == "Grep":
            pattern = inp.get("pattern", "?")
            path = inp.get("path", ".")
            print(f"\033[2m    Grep '{pattern}' in {path}\033[0m", flush=True)
        elif name == "Glob":
            pattern = inp.get("pattern", "?")
            print(f"\033[2m    Glob {pattern}\033[0m", flush=True)
        elif name == "Bash":
            cmd = inp.get("command", "?")
            print(f"\033[2m    $ {cmd}\033[0m", flush=True)
        else:
            print(f"\033[2m    {name} {json.dumps(inp)[:100]}\033[0m", flush=True)

    # ── Prompt builder ────────────────────────────────────────────

    def _build_review_prompt(self, pr: PRData, cl: dict, gate_context: dict) -> str:
        review_comments = ""
        if pr.review_comments:
            lines = []
            for c in pr.review_comments:
                reply = " (reply)" if c.get("in_reply_to_id") else ""
                lines.append(f"  - @{c['user']}{reply} on {c['path']}: {c['body'][:500]}")
            review_comments = "\n\nReview comments:\n" + "\n".join(lines)

        ownership = self._format_ownership(cl)

        gate_lines = []
        for g in gate_context["gates"]:
            status = "passed" if g["passed"] else "FAILED"
            gate_lines.append(f"  {g['gate']}: {status} — {g['message']}")
        gate_summary = "\n".join(gate_lines)

        gate_verdict = gate_context["gate_verdict"]
        constraint = ""
        if gate_verdict == "DENIED":
            constraint = "\nGates DENIED this PR. Your verdict MUST be REFUSE or ESCALATE. Explain why in the comment."
        elif gate_verdict == "AUTO-APPROVED":
            constraint = "\nGates auto-approved this PR (T0). Confirm or flag concerns in the comment."

        return textwrap.dedent(f"""\
            Review PR #{pr.number}: {pr.title}
            Author: {pr.author}
            Tier: {cl["tier"]} / {cl.get("t1_subclass", "")}
            Size: {pr.lines_total} lines ({pr.lines_added}+/{pr.lines_deleted}-), {len(pr.files)} files
            Scope: {cl["breadth"]}
            Commit type: {cl.get("commit_type") or "unknown"}

            {ownership}

            Gate results:
            {gate_summary}
            Gate verdict: {gate_verdict}
            {constraint}

            Changed files:
            {chr(10).join(f"  {f['filename']} (+{f['additions']}/-{f['deletions']})" for f in pr.files)}
            {review_comments}

            To see the diff, run: git diff {pr.base_sha}..{pr.head_sha}
            You can also diff individual files: git diff {pr.base_sha}..{pr.head_sha} -- <path>
        """)

    def _format_ownership(self, cl: dict) -> str:
        ownership = cl.get("ownership", {})
        teams = ownership.get("teams", [])
        if not teams:
            return "Ownership: no CODEOWNERS-soft match"
        summary = cl.get("ownership_summary", "")
        on_team = cl.get("author_on_owning_team", True)
        per_team = ownership.get("team_file_counts", {})
        lines = [f"Ownership: {summary}"]
        if per_team:
            lines.append(f"  Files per team: {json.dumps(per_team)}")
        if not on_team:
            lines.append("  NOTE: Author is NOT on the owning team")
        if ownership.get("cross_team"):
            lines.append("  NOTE: Cross-team change")
        return "\n".join(lines)
