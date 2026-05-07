#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "anthropic>=0.40",
# ]
# ///
# ruff: noqa: T201
"""Analyze a PR description for sensitive data and post a redacted suggestion.

Pipeline:
1. Fetch PR description via `gh pr view --json body`.
2. Run deterministic regex patterns (fast, offline-safe).
3. If regex finds any high-severity hit OR description is non-trivial, run
   Claude for semantic detection.
4. Combine findings, render a redacted suggestion, post a single PR comment
   with the redaction diff and a one-click "apply redaction" instruction.
5. Optionally auto-update the PR body when `--auto-redact` is passed
   (off by default — the comment route is friendlier).

Usage:
    uv run tools/pr-leak-guard/analyze_pr.py <pr_number> --repo PostHog/posthog
    uv run tools/pr-leak-guard/analyze_pr.py <pr_number> --auto-redact
    uv run tools/pr-leak-guard/analyze_pr.py --description-file desc.md  # local

The script exits 0 even when leaks are found — the surfacing is via a PR
comment, not CI failure, because PR descriptions get edited frequently and
we want to nudge, not block. Set `--block-on=block` to fail CI when a
secret-grade finding shows up (defaults: regex secret-blockers always
fail, LLM verdict 'block' fails).
"""

from __future__ import annotations

import sys
import json
import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Allow running as a script — sibling modules need to import cleanly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm_analyzer import (  # noqa: E402
    analyze as llm_analyze,
    llm_findings_to_findings,
)
from patterns import (  # noqa: E402
    Finding,
    find as find_patterns,
    has_blockers,
    redact,
    summarize,
)

COMMENT_MARKER = "<!-- pr-leak-guard:v1 -->"
MIN_DESCRIPTION_LEN_FOR_LLM = 80  # avoid LLM calls on near-empty descriptions


@dataclass
class AnalysisResult:
    pr_number: int
    description: str
    findings: list[Finding]
    llm_verdict: str
    llm_reasoning: str
    redacted: str

    @property
    def changed(self) -> bool:
        return self.redacted != self.description

    @property
    def has_blockers(self) -> bool:
        return has_blockers(self.findings)


def _fetch_pr_body(pr_number: int, repo: str) -> str:
    cmd = ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "body"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"gh pr view failed: {result.stderr.strip()}")
    return json.loads(result.stdout).get("body") or ""


def _strip_template_boilerplate(body: str) -> str:
    """Remove HTML comments and the empty section headers we never check."""
    # Removing comments avoids the LLM and regex from chasing the template's
    # own warning text ("DO NOT INCLUDE sensitive data...") and reporting
    # *that* as a finding.
    out_lines = []
    in_html_comment = False
    for line in body.splitlines():
        stripped = line.strip()
        if in_html_comment:
            if "-->" in stripped:
                in_html_comment = False
            continue
        if stripped.startswith("<!--") and "-->" not in stripped:
            in_html_comment = True
            continue
        if stripped.startswith("<!--") and "-->" in stripped:
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def analyze(description: str, *, skip_llm: bool = False) -> AnalysisResult:
    cleaned = _strip_template_boilerplate(description)
    regex_findings = find_patterns(cleaned)

    llm_verdict = "clean"
    llm_reasoning = ""
    llm_findings: list[Finding] = []
    if not skip_llm and len(cleaned.strip()) >= MIN_DESCRIPTION_LEN_FOR_LLM:
        llm_result = llm_analyze(cleaned)
        llm_verdict = llm_result.verdict
        llm_reasoning = llm_result.reasoning
        llm_findings = llm_findings_to_findings(llm_result, cleaned)

    combined = sorted(regex_findings + llm_findings)
    redacted = redact(cleaned, combined)

    return AnalysisResult(
        pr_number=0,
        description=cleaned,
        findings=combined,
        llm_verdict=llm_verdict,
        llm_reasoning=llm_reasoning,
        redacted=redacted,
    )


def _render_comment(result: AnalysisResult) -> str:
    """Render the PR comment body — single source of truth for what gets posted."""
    summary = summarize(result.findings)
    counts = summary["by_category"]
    top_categories = sorted(counts.items(), key=lambda kv: -kv[1])[:5]

    severity_emoji = "🛑" if result.has_blockers else "⚠️"
    title = "Possible secret leak detected" if result.has_blockers else "Possible sensitive data in PR description"

    if not result.findings:
        body = (
            f"{COMMENT_MARKER}\n"
            "### ✅ PR description scan clean\n\n"
            "No sensitive data detected in the description. Nothing for you to do.\n"
        )
        return body

    findings_table = "\n".join(f"| `{cat}` | {n} |" for cat, n in top_categories)

    suggested_diff = _build_suggestion_block(result.description, result.redacted)

    notes = []
    if result.llm_verdict != "clean" and result.llm_reasoning:
        notes.append(f"**LLM reviewer**: {_first_sentence(result.llm_reasoning)}")
    if result.has_blockers:
        notes.append(
            "🛑 **One or more findings look like secrets** — please rotate any keys "
            "you may have pasted, then update the PR description with the suggested redaction."
        )
    notes_block = "\n\n".join(notes) if notes else ""

    body = (
        f"{COMMENT_MARKER}\n"
        f"### {severity_emoji} {title}\n\n"
        "PostHog's repository is public, so PR descriptions are visible to anyone "
        "watching the repo. The scanner found patterns that look like internal or "
        "private references. Below is a redacted version of your description — "
        "please review and use **Edit** on the PR description if you agree.\n\n"
        "<details><summary>Findings by category</summary>\n\n"
        f"| Category | Count |\n| --- | --- |\n{findings_table}\n\n"
        "</details>\n\n"
        f"{notes_block}\n\n"
        "---\n"
        "<details><summary>📝 Suggested redacted description</summary>\n\n"
        f"```markdown\n{result.redacted}\n```\n"
        "</details>\n\n"
        f"<details><summary>🔍 Diff (what changes)</summary>\n\n```diff\n{suggested_diff}\n```\n</details>\n\n"
        "<sub>"
        f"Scanner: pr-leak-guard. {summary['total']} finding(s). "
        "False positives? Reply with `pr-leak-guard: ignore` to suppress this scan on subsequent edits."
        "</sub>\n"
    )
    return body


def _first_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    for sep in (". ", "\n"):
        i = text.find(sep)
        if i != -1:
            return text[: i + 1].strip()
    return text[:300]


def _build_suggestion_block(original: str, redacted: str) -> str:
    """Tiny line-level diff so a reader can see what would change.

    We keep this dependency-free (no `difflib`) for speed and minimal output.
    """
    import difflib

    diff = difflib.unified_diff(
        original.splitlines(keepends=False),
        redacted.splitlines(keepends=False),
        fromfile="original",
        tofile="redacted",
        lineterm="",
        n=1,
    )
    return "\n".join(diff)


def _existing_comment_id(pr_number: int, repo: str) -> int | None:
    """Find an existing pr-leak-guard comment so we update instead of duplicating."""
    cmd = [
        "gh",
        "api",
        f"repos/{repo}/issues/{pr_number}/comments",
        "--paginate",
        "--jq",
        f'.[] | select(.body | contains("{COMMENT_MARKER}")) | .id',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None
    ids = [int(line) for line in result.stdout.strip().splitlines() if line.strip().isdigit()]
    return ids[0] if ids else None


def _post_or_update_comment(pr_number: int, repo: str, body: str, dry_run: bool) -> None:
    if dry_run:
        print("--- DRY RUN: would post comment ---")
        print(body)
        return

    # Write the body to a temp file and pass via --body-file. Markdown
    # bodies regularly exceed ARGV size limits and contain shell
    # metacharacters; piping via stdin / a file avoids both pitfalls.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        body_path = fh.name

    try:
        existing = _existing_comment_id(pr_number, repo)
        if existing is not None:
            cmd = [
                "gh",
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/comments/{existing}",
                "-F",
                f"body=@{body_path}",
            ]
        else:
            cmd = [
                "gh",
                "pr",
                "comment",
                str(pr_number),
                "--repo",
                repo,
                "--body-file",
                body_path,
            ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to post comment: {result.stderr.strip()}")
    finally:
        Path(body_path).unlink(missing_ok=True)


def _ignore_label_present(pr_number: int, repo: str) -> bool:
    """Authors can opt out by adding the `pr-leak-guard:ignore` label."""
    cmd = ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "labels"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return False
    try:
        labels = json.loads(result.stdout).get("labels", [])
    except json.JSONDecodeError:
        return False
    return any(label.get("name") == "pr-leak-guard:ignore" for label in labels)


def _auto_redact_description(pr_number: int, repo: str, redacted: str, dry_run: bool) -> None:
    if dry_run:
        print("--- DRY RUN: would update PR body ---")
        print(redacted)
        return
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(redacted)
        body_path = fh.name
    try:
        cmd = ["gh", "pr", "edit", str(pr_number), "--repo", repo, "--body-file", body_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to update PR body: {result.stderr.strip()}")
    finally:
        Path(body_path).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a PR description for sensitive data")
    parser.add_argument("pr_number", type=int, nargs="?", help="PR number to scan")
    parser.add_argument("--repo", default="PostHog/posthog", help="GitHub repo (owner/name)")
    parser.add_argument(
        "--description-file",
        type=str,
        help="Read description from a file instead of GitHub (local testing)",
    )
    parser.add_argument(
        "--auto-redact",
        action="store_true",
        help="Update the PR body with the redacted version (default: comment only)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip the LLM stage (regex only — used in offline / no-API contexts)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the would-be comment to stdout instead of posting",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        help="Save analysis result JSON for downstream automation",
    )
    parser.add_argument(
        "--fail-on-block",
        action="store_true",
        help="Exit non-zero when block-severity findings are present",
    )
    args = parser.parse_args()

    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8")
        pr_number = args.pr_number or 0
    else:
        if not args.pr_number:
            parser.error("pr_number is required when --description-file is not provided")
        description = _fetch_pr_body(args.pr_number, args.repo)
        pr_number = args.pr_number

    if pr_number and args.repo and not args.description_file:
        if _ignore_label_present(pr_number, args.repo):
            print("pr-leak-guard:ignore label present — skipping scan.")
            return 0

    result = analyze(description, skip_llm=args.no_llm)
    result.pr_number = pr_number

    summary = summarize(result.findings)
    print(json.dumps(summary, indent=2))
    if result.llm_verdict != "clean":
        print(f"\nLLM verdict: {result.llm_verdict}")
        print(f"LLM reasoning: {result.llm_reasoning}")

    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(
                {
                    "pr_number": pr_number,
                    "summary": summary,
                    "llm_verdict": result.llm_verdict,
                    "llm_reasoning": result.llm_reasoning,
                    "has_blockers": result.has_blockers,
                    "redacted": result.redacted,
                },
                indent=2,
            )
        )

    if pr_number and not args.description_file:
        comment_body = _render_comment(result)
        # Only post / update when there's something to say. Don't spam
        # with "looks clean" follow-ups on every edit; only update an
        # existing scan comment to clear it.
        existing_id = _existing_comment_id(pr_number, args.repo)
        if result.findings or existing_id is not None:
            _post_or_update_comment(pr_number, args.repo, comment_body, args.dry_run)

        if args.auto_redact and result.changed:
            _auto_redact_description(pr_number, args.repo, result.redacted, args.dry_run)

    if args.dry_run and not pr_number:
        print(_render_comment(result))

    if args.fail_on_block and result.has_blockers:
        print("\n::error::Block-severity findings detected — failing CI.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
