#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "claude-agent-sdk",
#     "anthropic",
#     "posthoganalytics",
# ]
# ///
# ruff: noqa: T201
"""AI-assisted PR approval agent.

Usage:
    uv run tools/pr-approval-agent/review_pr.py <pr_number> [--dry-run] [--output-json path]

Runs deterministic gates (deny-list, ownership, tier classification),
then — if eligible — calls Claude for evidence-bundle review and
second-pass audit.

Requires `gh` CLI authenticated and ANTHROPIC_API_KEY in env.
"""

import json
import time
import argparse
from dataclasses import dataclass, field
from pathlib import Path

from gates import (
    MAX_FILES,
    MAX_LINES,
    assign_tier,
    classify_files,
    detect_deny_categories,
    detect_ownership,
    has_ci_workflow_changes,
    has_dependency_changes,
    is_allow_listed_only,
    parse_codeowners_soft,
    parse_conventional_commit,
    scope_breadth,
    t1_risk_subclass,
    test_only,
)
from github import PRData, check_team_membership, fetch_pr
from reviewer import Reviewer

try:
    import os

    import posthoganalytics

    posthoganalytics.api_key = os.environ.get("POSTHOG_API_KEY", "")  # ty: ignore[invalid-assignment]
    posthoganalytics.host = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")  # ty: ignore[invalid-assignment]
    _POSTHOG_AVAILABLE = bool(posthoganalytics.api_key)
except ImportError:
    _POSTHOG_AVAILABLE = False

# ── Repo root detection ──────────────────────────────────────────


def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("Cannot find git repo root from script location")


REPO_ROOT = _repo_root()
CODEOWNERS_SOFT = REPO_ROOT / ".github" / "CODEOWNERS-soft"


# ── Terminal formatting ──────────────────────────────────────────


def _ok(msg: str) -> str:
    return f"  \033[32m✓\033[0m {msg}"


def _warn(msg: str) -> str:
    return f"  \033[33m⚠\033[0m {msg}"


def _fail(msg: str) -> str:
    return f"  \033[31m✗\033[0m {msg}"


def _bold(msg: str) -> str:
    return f"\033[1m{msg}\033[0m"


def _dim(msg: str) -> str:
    return f"\033[2m{msg}\033[0m"


# ── Gate result ──────────────────────────────────────────────────


@dataclass
class GateResult:
    gate: str
    passed: bool
    message: str
    details: dict = field(default_factory=dict)


# ── Pipeline ─────────────────────────────────────────────────────


class Pipeline:
    """Orchestrates the full PR review: fetch → classify → gates → LLM review."""

    def __init__(self, pr_number: int, repo: str, *, dry_run: bool = False, verbose: bool = False):
        self.pr_number = pr_number
        self.repo = repo
        self.dry_run = dry_run
        self.verbose = verbose
        self.pr: PRData | None = None
        self.classification: dict = {}
        self.gate_results: list[GateResult] = []
        self.reviewer_output: dict | None = None
        self.final_verdict: str = ""

    def run(self) -> str:
        """Run the full pipeline, return final verdict string."""
        self._fetch()
        self._classify()
        self._run_gates()

        gate_verdict = self._gate_verdict()

        if self.dry_run:
            self.final_verdict = "DRY-RUN"
            return self.final_verdict

        self._llm_review(gate_verdict)
        return self.final_verdict

    def _gate_verdict(self) -> str:
        """Determine what gates say — this is authoritative."""
        if self._any_gate_denied():
            return "DENIED"
        if self.classification["tier"] == "T0-deterministic":
            return "AUTO-APPROVED"
        return "PENDING"

    # ── Steps ────────────────────────────────────────────────────

    def _fetch(self) -> None:
        print(_dim("Fetching PR data..."))
        self.pr = fetch_pr(self.pr_number, self.repo, repo_root=REPO_ROOT)
        print(_dim(f"  {self.pr.title}"))
        print(
            _dim(
                f"  by @{self.pr.author} | {self.pr.state} | {len(self.pr.files)} files | {len(self.pr.review_comments)} comments"
            )
        )
        print()

    def _classify(self) -> None:
        pr = self.pr
        file_paths = pr.file_paths
        file_info = classify_files(file_paths)
        categories = file_info["categories"]
        top_dirs = file_info["top_dirs"]
        breadth = scope_breadth(top_dirs)
        cc = parse_conventional_commit(pr.title)
        deny = detect_deny_categories(file_paths, pr.title)
        allow_only = is_allow_listed_only(file_paths)
        is_test = test_only(categories)
        ownership_rules = parse_codeowners_soft(CODEOWNERS_SOFT)
        ownership = detect_ownership(file_paths, ownership_rules)

        tier = assign_tier(
            deny_categories=deny,
            allow_listed_only=allow_only,
            is_test_only=is_test,
            has_new_files=pr.has_new_files,
            lines_total=pr.lines_total,
            files_changed=len(file_paths),
            breadth=breadth,
            commit_type=cc["type"],
        )
        subclass = ""
        if tier == "T1-agent":
            subclass = t1_risk_subclass(
                lines_total=pr.lines_total,
                files_changed=len(file_paths),
                breadth=breadth,
            )

        self.classification = {
            "tier": tier,
            "t1_subclass": subclass,
            "breadth": breadth,
            "commit_type": cc["type"],
            "commit_scope": cc["scope"],
            "categories": categories,
            "deny_categories": deny,
            "allow_listed_only": allow_only,
            "is_test_only": is_test,
            "has_dep_changes": has_dependency_changes(file_paths),
            "has_ci_changes": has_ci_workflow_changes(file_paths),
            "ownership": ownership,
        }

    def _run_gates(self) -> None:
        print(_bold("Gates"))
        gates = [
            ("prerequisites", self._check_prerequisites),
            ("deny-list", self._check_deny_list),
            ("size", self._check_size),
            ("tier", self._check_tier),
        ]
        for name, check in gates:
            passed, message = check()
            result = GateResult(name, passed, message)
            self.gate_results.append(result)
            print(_ok(f"{name}: {message}") if passed else _fail(f"{name}: {message}"))

        ownership = self._summarize_ownership()
        print(_dim(f"  ownership: {ownership}"))

    def _any_gate_denied(self) -> bool:
        return any(not r.passed for r in self.gate_results)

    def _check_prerequisites(self) -> tuple[bool, str]:
        pr = self.pr
        issues = []
        if pr.draft:
            issues.append("PR is still in draft")
        if pr.mergeable_state == "dirty":
            issues.append("merge conflicts present")

        latest_review_per_user: dict[str, str] = {}
        for r in pr.reviews:
            latest_review_per_user[r["user"]] = r["state"]
        changes_requested = [u for u, s in latest_review_per_user.items() if s == "CHANGES_REQUESTED"]
        if changes_requested:
            issues.append(f"changes requested by: {', '.join(changes_requested)}")

        # CI failures are not a hard gate — CI is its own gate and the
        # agent is often triggered before all checks finish.

        if issues:
            return False, "; ".join(issues)
        return True, "all clear"

    def _check_deny_list(self) -> tuple[bool, str]:
        deny = self.classification["deny_categories"]
        if deny:
            return False, f"matches: {', '.join(deny)}"
        return True, "no deny categories matched"

    def _summarize_ownership(self) -> str:
        """Build ownership context for the LLM (not a hard gate)."""
        ownership = self.classification["ownership"]
        if ownership["team_count"] == 0:
            self.classification["ownership_summary"] = "no owned paths touched"
            return self.classification["ownership_summary"]

        teams = ownership["teams"]
        author = self.pr.author
        author_teams = []
        for team_raw in teams:
            team_slug = team_raw.split("/")[-1]
            if check_team_membership(author, team_slug):
                author_teams.append(team_raw)

        parts = [f"touches {', '.join(teams)}"]
        if author_teams:
            parts.append(f"author {author} is on {', '.join(author_teams)}")
        else:
            parts.append(f"author {author} is not on any owning team")
        if ownership["cross_team"]:
            parts.append("cross-team change")

        self.classification["ownership_summary"] = "; ".join(parts)
        self.classification["author_on_owning_team"] = len(author_teams) > 0
        return self.classification["ownership_summary"]

    def _check_size(self) -> tuple[bool, str]:
        lines = self.pr.lines_total
        files = len(self.pr.files)
        binary_count = sum(1 for f in self.pr.files if f.get("binary"))
        suffix = f", {binary_count} binary" if binary_count else ""
        if lines > MAX_LINES or files > MAX_FILES:
            return (
                False,
                f"too large for auto-review ({lines}L, {files}F{suffix} — ceiling is {MAX_LINES}L / {MAX_FILES}F)",
            )
        return True, f"{lines}L, {files}F{suffix} within ceiling"

    def _check_tier(self) -> tuple[bool, str]:
        cl = self.classification
        tier_label = cl["tier"]
        if cl["t1_subclass"]:
            tier_label += f" / {cl['t1_subclass']}"
        summary = f"{tier_label} ({self.pr.lines_total}L, {len(self.pr.files)}F, {cl['breadth']}, {cl['commit_type'] or 'unknown'})"

        if cl["tier"] == "T2-never":
            return False, f"classified as T2-never: {summary}"
        if cl["tier"] == "T0-deterministic":
            return True, f"T0 auto-approve: {summary}"
        return True, summary

    def _llm_review(self, gate_verdict: str) -> None:
        print(f"\n{_bold('LLM Review')}")
        reviewer = Reviewer(REPO_ROOT, verbose=self.verbose)

        gate_context = {
            "gate_verdict": gate_verdict,
            "gates": [{"gate": g.gate, "passed": g.passed, "message": g.message} for g in self.gate_results],
        }

        print(_dim("  Calling reviewer..."))
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.reviewer_output = reviewer.review(
                    self.pr,
                    self.classification,
                    gate_context,
                )
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(_warn(f"Reviewer failed (attempt {attempt + 1}/{max_retries}): {e}"))
                    print(_dim(f"  Retrying in {wait}s..."))
                    time.sleep(wait)
                else:
                    print(_fail(f"Reviewer failed after {max_retries} attempts: {e}"))
                    self.reviewer_output = {
                        "verdict": "ESCALATE",
                        "reasoning": f"Review agent failed after {max_retries} attempts — needs human review.",
                        "risk": "unknown",
                        "issues": [str(e)],
                    }

        llm_verdict = self.reviewer_output.get("verdict", "UNKNOWN")
        print(f"  Verdict: {llm_verdict}")
        print(f"  Reasoning: {self.reviewer_output.get('reasoning', '?')}")

        issues = self.reviewer_output.get("issues", [])
        for issue in issues:
            print(_warn(f"  {issue}"))

        # Gates are authoritative — LLM can tighten but never loosen
        if gate_verdict == "DENIED":
            self.final_verdict = "REFUSED"
            print(f"\n{_fail('REFUSED')} — gates denied")
        elif gate_verdict == "AUTO-APPROVED" and llm_verdict in ("REFUSE", "ESCALATE"):
            self.final_verdict = "ESCALATE"
            print(f"\n{_warn('ESCALATE')} — gates auto-approved but LLM disagrees")
        elif llm_verdict == "APPROVE":
            self.final_verdict = "APPROVED"
            print(f"\n{_ok('APPROVED')}")
        elif llm_verdict == "REFUSE":
            self.final_verdict = "REFUSED"
            print(f"\n{_fail('REFUSED')}")
        else:
            self.final_verdict = "ESCALATE"
            print(f"\n{_warn('ESCALATE')} — needs human review")

        self._capture_review_completed(gate_verdict, llm_verdict)

    def _capture_review_completed(self, gate_verdict: str, llm_verdict: str) -> None:
        """Send a stamphog_review_completed event with all verdict data."""
        if not _POSTHOG_AVAILABLE:
            return

        cl = self.classification
        pr = self.pr
        posthoganalytics.capture(
            distinct_id=pr.author,
            event="stamphog_review_completed",
            properties={
                "ai_product": "stamphog",
                "stamphog_pr_number": pr.number,
                "stamphog_repo": pr.repo,
                "stamphog_author": pr.author,
                "stamphog_pr_title": pr.title,
                "stamphog_tier": cl.get("tier", ""),
                "stamphog_t1_subclass": cl.get("t1_subclass", ""),
                "stamphog_breadth": cl.get("breadth", ""),
                "stamphog_commit_type": cl.get("commit_type") or "",
                "stamphog_files_changed": len(pr.files),
                "stamphog_lines_total": pr.lines_total,
                "stamphog_gate_verdict": gate_verdict,
                "stamphog_llm_verdict": llm_verdict,
                "stamphog_final_verdict": self.final_verdict,
                "stamphog_llm_reasoning": (self.reviewer_output or {}).get("reasoning", ""),
                "stamphog_llm_risk": (self.reviewer_output or {}).get("risk", ""),
                "stamphog_llm_issues": (self.reviewer_output or {}).get("issues", []),
            },
        )

    # ── Output ───────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "pr_number": self.pr.number,
            "repo": self.pr.repo,
            "title": self.pr.title,
            "author": self.pr.author,
            "head_sha": self.pr.head_sha,
            "classification": {
                "tier": self.classification["tier"],
                "t1_subclass": self.classification.get("t1_subclass", ""),
                "lines_total": self.pr.lines_total,
                "files_changed": len(self.pr.files),
                "breadth": self.classification["breadth"],
                "commit_type": self.classification.get("commit_type"),
                "deny_categories": self.classification.get("deny_categories", []),
                "ownership": self.classification.get("ownership", {}),
            },
            "gates": [
                {"gate": g.gate, "passed": g.passed, "message": g.message} for g in self.gate_results if g is not None
            ],
            "reviewer": self.reviewer_output,
            "final_verdict": self.final_verdict,
        }

    def save_json(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        print(_dim(f"\nSaved to {path}"))


# ── CLI ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AI PR approval agent")
    parser.add_argument("pr_number", type=int, help="PR number to review")
    parser.add_argument("--repo", default="PostHog/posthog", help="GitHub repo (owner/name)")
    parser.add_argument("--dry-run", action="store_true", help="Run gates only, skip LLM calls")
    parser.add_argument("--output-json", type=str, help="Save full result to JSON file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show agent tool calls during review")
    args = parser.parse_args()

    print(_bold(f"\nReviewing PR #{args.pr_number} ({args.repo})\n"))

    pipeline = Pipeline(args.pr_number, args.repo, dry_run=args.dry_run, verbose=args.verbose)
    verdict = pipeline.run()

    if verdict == "DRY-RUN":
        print(f"\n{_dim('DRY RUN — would proceed to LLM review')}")

    if args.output_json:
        pipeline.save_json(args.output_json)

    if _POSTHOG_AVAILABLE:
        posthoganalytics.flush()


if __name__ == "__main__":
    main()
