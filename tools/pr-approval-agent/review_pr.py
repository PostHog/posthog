#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "claude-agent-sdk",
#     "anthropic",
#     "posthoganalytics",
#     "pyyaml",
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

import os
import json
import time
import argparse
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from familiarity import AuthorFamiliarity, compute_familiarity, familiarity_evidence
from gates import (
    MAX_FILES,
    MAX_LINES,
    POLICY,
    assign_tier,
    category_fully_exempt,
    classify_files,
    dependency_manifests_without_lockfile,
    detect_deny_categories,
    detect_ownership,
    detect_title_scrutiny_flags,
    has_ci_workflow_changes,
    has_dependency_changes,
    is_allow_listed_only,
    parse_codeowners_soft,
    parse_conventional_commit,
    scope_breadth,
    substantive_size,
    t1_risk_subclass,
    test_only,
)
from github import TRUSTED_REACTOR_BOTS, PRData, check_team_membership, fetch_pr, write_pr_diff
from manifest_risk import manifest_script_changes
from migration_risk import migration_check_pending, safe_migration_files
from policy import EffectivePolicy, ScopeBudget, _sanitize_untrusted, repo_root, resolve
from reviewer import Reviewer

try:
    import posthoganalytics

    posthoganalytics.api_key = os.environ.get("POSTHOG_API_KEY", "")  # ty: ignore[invalid-assignment]
    posthoganalytics.host = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")  # ty: ignore[invalid-assignment]
    _POSTHOG_AVAILABLE = bool(posthoganalytics.api_key)
except ImportError:
    _POSTHOG_AVAILABLE = False

# ── Repo root detection ──────────────────────────────────────────

REPO_ROOT = repo_root()
CODEOWNERS_SOFT = REPO_ROOT / ".github" / "CODEOWNERS-soft"


def _head_commit_sha() -> str:
    """HEAD sha of the checked-out policy tree, or 'unknown' if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


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


# ── Error classification ─────────────────────────────────────────

# Patterns that indicate non-retryable failures (agent limitations, not infra).
_NON_RETRYABLE_PATTERNS = (
    "Reached maximum number of turns",
    "could not produce valid structured output",
)


def _is_retryable_error(err_msg: str) -> bool:
    """Return True if the error looks like an infrastructure/transient issue
    that is worth retrying (API timeouts, rate limits, overload).
    Return False for non-retryable errors like turn-limit exhaustion."""
    return not any(pattern in err_msg for pattern in _NON_RETRYABLE_PATTERNS)


# Reviewer bots put 👀 on a PR while reviewing and swap it for a verdict
# reaction within minutes. Stamphog is usually triggered at the same moment
# (label applied at PR open), so an 👀 at fetch time is almost always a race
# with a bot mid-review, not a lasting state — poll until it clears instead
# of refusing. Budget must leave room for the LLM review inside the
# workflow job timeout.
BOT_REVIEW_WAIT_BUDGET_SECONDS = 300
BOT_REVIEW_POLL_SECONDS = 30

# A bot 👀 much older than any real review is a crashed reviewer, not an
# in-flight one — reactions never expire and a human can't remove another
# app's reaction, so without this cutoff a wedged bot would make every run
# WAIT forever. Reactions missing a timestamp count as fresh (fail toward
# waiting).
BOT_EYES_MAX_AGE_SECONDS = 45 * 60


def _reaction_age_seconds(created_at: str | None) -> float:
    if not created_at:
        return 0.0
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return 0.0
    return (datetime.now(UTC) - created).total_seconds()


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
        self._wait_refetched_pr = False
        self.pr: PRData | None = None
        self.classification: dict = {}
        self.effective_policy: EffectivePolicy | None = None
        self._diff_path: Path | None = None
        self.gate_results: list[GateResult] = []
        self.reviewer_output: dict | None = None
        self.final_verdict: str = ""

    def run(self) -> str:
        """Run the full pipeline, return final verdict string."""
        self._fetch()

        if self.pr.author_is_bot:
            return self._refuse_bot_author()

        gate_verdict = self._classify_and_gate()

        if self._only_pending_migration_check():
            return self._refuse_pending_migration_check()

        if self.dry_run:
            self.final_verdict = "DRY-RUN"
            return self.final_verdict

        # Gate denials skip the wait: a refusal can't approve over an
        # in-flight review, so waiting would only burn runner minutes before
        # the inevitable REFUSE. The wait refetches the PR, so on the paths
        # that did wait, re-derive classification and gates from fresh data.
        if gate_verdict != "DENIED":
            wait_verdict = self._handle_in_flight_bot_reviews()
            if wait_verdict:
                return wait_verdict
            if self._wait_refetched_pr:
                gate_verdict = self._classify_and_gate()
                if self._only_pending_migration_check():
                    return self._refuse_pending_migration_check()

        try:
            self._maybe_compute_familiarity()
            self._llm_review(gate_verdict)
        finally:
            if self._diff_path is not None:
                self._diff_path.unlink(missing_ok=True)
        return self.final_verdict

    def _classify_and_gate(self) -> str:
        self.gate_results = []
        self._classify()
        self._run_gates()
        return self._gate_verdict()

    def _only_pending_migration_check(self) -> bool:
        """True when the only thing blocking approval is a pending Migration risk check.

        Lets us emit a specific deny reason ("wait for the check, re-label")
        instead of the generic deny-list one. Other denies (auth, crypto) or
        gate failures (size, prerequisites) won't clear when the analyzer
        finishes, so we shouldn't promise a re-label will help.
        """
        if self.classification.get("deny_categories", []) != ["migrations"]:
            return False
        if any(not r.passed and r.gate != "deny-list" for r in self.gate_results):
            return False
        return migration_check_pending(self.pr.check_runs, self.pr.file_paths)

    def _refuse_bot_author(self) -> str:
        """Hard gate: stamphog never reviews bot-authored PRs.

        A human applying the stamphog label can't override this — bot output
        isn't a trusted basis for an auto-approval. The workflow already gates
        the review job on a non-bot author; this is the defense-in-depth layer
        for any manual or out-of-band invocation.
        """
        self.final_verdict = "REFUSED"
        self.reviewer_output = {
            "verdict": "REFUSE",
            "reasoning": (
                f"@{self.pr.author} is a bot — stamphog does not review "
                "bot-authored PRs. This change needs a human reviewer."
            ),
            "risk": "unknown",
            "issues": [],
        }
        print(f"\n{_fail('REFUSED')} — bot author (@{self.pr.author}); stamphog skips bot-authored PRs")
        self._capture_review_completed("DENIED", "BOT-AUTHOR")
        return self.final_verdict

    def _in_flight_bot_reviewers(self) -> list[str]:
        """Allowlisted reviewer bots with a fresh 👀 reaction on the PR."""
        return sorted(
            {
                r["user"]
                for r in self.pr.pr_reactions
                if r["emoji"] == "👀"
                and r["user"].lower() in TRUSTED_REACTOR_BOTS
                and _reaction_age_seconds(r.get("created_at")) <= BOT_EYES_MAX_AGE_SECONDS
            }
        )

    def _handle_in_flight_bot_reviews(self) -> str | None:
        """Wait out the reviewer-bot 👀 race; WAIT if a bot is still reviewing.

        Returns None when no bot review is (or remains) in flight. Human 👀
        reactions are not waited on — humans take longer than any polling
        budget, and the LLM refuses over them with a clear message instead.
        The WAIT verdict keeps the stamphog label (like ERROR) so the review
        retries on the next push rather than demanding a human re-label.
        """
        bots = self._in_flight_bot_reviewers()
        if not bots:
            return None

        deadline = time.monotonic() + BOT_REVIEW_WAIT_BUDGET_SECONDS
        while time.monotonic() < deadline:
            print(_warn(f"in-flight bot review ({', '.join(bots)}) — waiting {BOT_REVIEW_POLL_SECONDS}s"))
            time.sleep(BOT_REVIEW_POLL_SECONDS)
            try:
                self._fetch()
            except Exception as exc:
                print(_warn(f"refetch failed ({exc}); treating as still in flight"))
                continue
            self._wait_refetched_pr = True
            bots = self._in_flight_bot_reviewers()
            if not bots:
                return None

        bot_list = ", ".join(f"@{b}" for b in bots)
        self.final_verdict = "WAIT"
        self.reviewer_output = {
            "verdict": "WAIT",
            "reasoning": (
                f"{bot_list} still {'have' if len(bots) > 1 else 'has'} a review in flight (👀) after "
                f"{BOT_REVIEW_WAIT_BUDGET_SECONDS // 60} minutes — not approving over an "
                "unfinished review. The `stamphog` label has been kept; the review re-runs "
                "on the next push, or remove and re-apply the label once the reviewer finishes."
            ),
            "risk": "unknown",
            "issues": [],
        }
        print(f"\n{_warn('WAIT')} — bot review still in flight ({bot_list}); label retained for retry")
        self._capture_review_completed("SKIPPED", "WAIT")
        return self.final_verdict

    def _refuse_pending_migration_check(self) -> str:
        self.final_verdict = "REFUSED"
        self.reviewer_output = {
            "verdict": "REFUSE",
            "reasoning": (
                "The `Migration risk` check has not completed for this commit. "
                "Wait for it to finish (visible in the PR's Checks tab), then "
                "re-apply the `stamphog` label to retry."
            ),
            "risk": "unknown",
            "issues": [],
        }
        print(f"\n{_warn('REFUSED')} — Migration risk check pending; re-label after it completes")
        self._capture_review_completed("DENIED", "PENDING-MIGRATION-CHECK")
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
        safe_migrations = safe_migration_files(pr.check_runs, file_paths)
        deny = detect_deny_categories(file_paths, ignored_files=safe_migrations)
        dep_manifests = dependency_manifests_without_lockfile(file_paths)
        # Deterministic first line for the manifest scripts risk: an edit to
        # scripts/lifecycle/build keys hard-denies rather than resting solely
        # on the reviewer prompt's REFUSE instruction.
        risky_manifests = (
            manifest_script_changes(dep_manifests, pr.base_sha, pr.head_sha, REPO_ROOT) if dep_manifests else []
        )
        if risky_manifests and "deps_toolchain" not in deny:
            deny = sorted([*deny, "deps_toolchain"])
        title_flags = [
            c
            for c in detect_title_scrutiny_flags(pr.title)
            if c not in deny and not category_fully_exempt(c, file_paths)
        ]
        # Dependency manifests are .json/.toml/.cfg so they'd otherwise ride
        # the allow-list into the T0 fast path — but manifest scripts execute
        # in CI, so they get full T1 scrutiny even though they no longer deny.
        # Both checks matter: has_dependency_changes catches lockfile-paired
        # manifests, dependency_manifests_without_lockfile catches the rest
        # (tsconfig, setup.py/.cfg) that the reviewer's scripts guard covers.
        allow_only = is_allow_listed_only(file_paths) and not has_dependency_changes(file_paths) and not dep_manifests
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

        # Resolve any per-folder override for this PR's file set once. Its
        # effective size gate feeds _check_size; its advisory prose (untrusted)
        # is threaded to the reviewer prompt; its provenance goes in the bundle.
        self.effective_policy = resolve(POLICY, file_paths)

        self.classification = {
            "tier": tier,
            "t1_subclass": subclass,
            "breadth": breadth,
            "commit_type": cc["type"],
            "commit_scope": cc["scope"],
            "categories": categories,
            "deny_categories": deny,
            "title_scrutiny_flags": title_flags,
            "safe_migration_files": sorted(safe_migrations),
            "allow_listed_only": allow_only,
            "is_test_only": is_test,
            "has_dep_changes": has_dependency_changes(file_paths),
            "dep_manifests_without_lockfile": dep_manifests,
            "manifest_script_changes": risky_manifests,
            "has_ci_changes": has_ci_workflow_changes(file_paths),
            "ownership": ownership,
            "folder_policy_prose": self.effective_policy.folder_prose,
            # Judgment-layer signal, filled in later only for the T1-agent path
            # (see _maybe_compute_familiarity). None here keeps every other path
            # - and the reviewer prompt - byte-identical to before.
            "familiarity": None,
        }

    def _maybe_compute_familiarity(self) -> None:
        """Attach the author-familiarity signal for the T1-agent path only.

        Judgment layer only - never touches gates, and any failure leaves the
        signal absent (None) so behavior stays exactly as before. T0 skips the
        LLM and T2 is a deny, so neither benefits from the signal.
        """
        if self.classification.get("tier") != "T1-agent":
            return
        self.classification["familiarity"] = self._compute_familiarity()

    def _compute_familiarity(self) -> AuthorFamiliarity | None:
        pr = self.pr
        try:
            return compute_familiarity(
                author_login=pr.author,
                diff_path=self._ensure_diff_path(),
                base_sha=pr.base_sha,
                head_sha=pr.head_sha,
                repo=self.repo,
                repo_root=REPO_ROOT,
                thresholds=POLICY.familiarity,
            )
        except Exception as exc:
            print(_warn(f"familiarity computation failed ({exc}); continuing without the signal"))
            return None

    def _ensure_diff_path(self) -> Path:
        """Write the PR diff once per run; familiarity and the reviewer share it.

        One producer keeps the two consumers grading the same diff. run() owns
        cleanup so the file never lingers in the repo working tree.
        """
        if self._diff_path is None:
            self._diff_path = write_pr_diff(
                self.pr.base_sha, self.pr.head_sha, REPO_ROOT / ".pr-review-diff.patch", REPO_ROOT
            )
        return self._diff_path

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
        risky = self.classification.get("manifest_script_changes", [])
        if risky:
            return False, f"matches: {', '.join(deny)} (scripts/hooks changed in {', '.join(risky)})"
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
        lines, files = substantive_size(self.pr.files)
        max_lines = self.effective_policy.max_lines if self.effective_policy else MAX_LINES
        binary_count = sum(1 for f in self.pr.files if f.get("binary"))
        exempt_files = len(self.pr.files) - files
        suffix_parts = []
        if binary_count:
            suffix_parts.append(f"{binary_count} binary")
        if exempt_files:
            suffix_parts.append(f"{self.pr.lines_total}L/{len(self.pr.files)}F incl. docs/generated/snapshots")
        suffix = (", " + "; ".join(suffix_parts)) if suffix_parts else ""
        if lines > max_lines:
            return (
                False,
                f"too large for auto-review ({lines}L, {files}F substantive{suffix} — ceiling is {max_lines}L)",
            )
        # Mixed PRs get mixed leniency: each file counts against the budget of
        # the scope governing it (a folder override or the global pool), so a
        # folder's higher ceiling covers its own files and nothing else.
        for scope in self._size_scopes():
            in_scope = set(scope.files)
            _, scope_files = substantive_size([f for f in self.pr.files if f["filename"] in in_scope])
            if scope_files > scope.max_files:
                where = scope.path or "global"
                return (
                    False,
                    f"too large for auto-review ({scope_files}F substantive in {where} — "
                    f"ceiling is {scope.max_files}F; {lines}L, {files}F total{suffix})",
                )
        return True, f"{lines}L, {files}F substantive{suffix} — within ceiling"

    def _size_scopes(self) -> tuple[ScopeBudget, ...]:
        if self.effective_policy is not None:
            return self.effective_policy.scopes
        all_files = tuple(f["filename"] for f in self.pr.files)
        return (ScopeBudget(path=None, max_files=MAX_FILES, files=all_files),)

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
        # Outside the retry loop: a diff-write hiccup must not masquerade as a
        # retryable reviewer failure and burn the backoff budget.
        diff_path = self._ensure_diff_path()

        gate_context = {
            "gate_verdict": gate_verdict,
            "gates": [{"gate": g.gate, "passed": g.passed, "message": g.message} for g in self.gate_results],
        }

        print(_dim("  Calling reviewer..."))
        max_retries = 3
        reviewer_unavailable = False
        for attempt in range(max_retries):
            try:
                self.reviewer_output = reviewer.review(
                    self.pr,
                    self.classification,
                    gate_context,
                    diff_path=diff_path,
                )
                break
            except Exception as e:
                err_str = str(e)
                is_retryable = _is_retryable_error(err_str)

                if is_retryable and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(_warn(f"Reviewer failed (attempt {attempt + 1}/{max_retries}): {e}"))
                    print(_dim(f"  Retrying in {wait}s..."))
                    time.sleep(wait)
                else:
                    reviewer_unavailable = True
                    if is_retryable:
                        print(_fail(f"Reviewer failed after {max_retries} attempts: {e}"))
                        print(
                            _warn(
                                "  This is an LLM backend failure (credentials, credit, or outage), "
                                "not a verdict on the PR. Check the STAMPHOG_ANTHROPIC_API_KEY "
                                "secret (or local ANTHROPIC_API_KEY)."
                            )
                        )
                        self.reviewer_output = {
                            "verdict": "ERROR",
                            "reasoning": (
                                "The review agent couldn't reach its LLM backend — an infrastructure "
                                "or credentials issue, not a problem with this PR. The `stamphog` label "
                                "has been kept; the review retries automatically on the next push, or "
                                "re-apply the label once the backend recovers."
                            ),
                            "risk": "unknown",
                            "issues": [err_str],
                        }
                    else:
                        print(_fail(f"Reviewer hit a non-retryable error: {e}"))
                        self.reviewer_output = {
                            "verdict": "ERROR",
                            "reasoning": (
                                "The review agent could not complete its analysis for this PR "
                                "(likely too complex for the allocated turn budget). "
                                "The `stamphog` label has been kept; a human review is needed."
                            ),
                            "risk": "unknown",
                            "issues": [err_str],
                        }
                    break

        llm_verdict = self.reviewer_output.get("verdict", "UNKNOWN")
        print(f"  Verdict: {llm_verdict}")
        print(f"  Reasoning: {self.reviewer_output.get('reasoning', '?')}")

        issues = self.reviewer_output.get("issues", [])
        for issue in issues:
            print(_warn(f"  {issue}"))

        # Gates are authoritative — LLM can tighten but never loosen. A real
        # gate denial outranks an unavailable reviewer: still REFUSE (and let
        # the label strip), because the deny is deterministic and actionable.
        if gate_verdict == "DENIED":
            self.final_verdict = "REFUSED"
            print(f"\n{_fail('REFUSED')} — gates denied")
        elif reviewer_unavailable:
            # Distinct from a substantive REFUSE/ESCALATE: the workflow keeps
            # the label so a transient outage doesn't drop it across every PR.
            self.final_verdict = "ERROR"
            print(f"\n{_warn('ERROR')} — review agent unavailable; label retained for retry")
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
                "stamphog_pr_reactions_count": len(pr.pr_reactions),
                "stamphog_title_scrutiny_flags": cl.get("title_scrutiny_flags", []),
                "stamphog_gate_verdict": gate_verdict,
                "stamphog_llm_verdict": llm_verdict,
                "stamphog_final_verdict": self.final_verdict,
                "stamphog_llm_reasoning": (self.reviewer_output or {}).get("reasoning", ""),
                "stamphog_llm_risk": (self.reviewer_output or {}).get("risk", ""),
                "stamphog_llm_issues": (self.reviewer_output or {}).get("issues", []),
            },
        )

    # ── Output ───────────────────────────────────────────────────

    def _render_review_body(self) -> str | None:
        """The verdict comment body: reasoning first, judgment bullets, mechanics folded.

        Judgment leads and the gate mechanics (budgets, tier, policy version)
        stay inside a collapsed details block. Built only from GFM constructs a
        GitHub comment actually renders.
        """
        if self.reviewer_output is None:
            return None
        reasoning = str(self.reviewer_output.get("reasoning", "")).strip()

        bullets: list[str] = []
        fam = self.classification.get("familiarity")
        if fam is not None and fam.band in ("STRONG", "MODERATE"):
            bullets.append(
                f"Author wrote {fam.blame_overlap_pct:.0f}% of the modified lines and has "
                f"{fam.prior_prs_in_paths} merged PRs in these paths (familiarity {fam.band})."
            )
        head_reviewers = sorted(
            {
                _sanitize_untrusted(r["user"], max_len=50)
                for r in self.pr.reviews
                if r.get("is_current_head") and r.get("state") in ("APPROVED", "COMMENTED")
            }
        )
        thumbs = sorted(
            {_sanitize_untrusted(r["user"], max_len=50) for r in self.pr.pr_reactions if r.get("emoji") == "👍"}
        )
        if head_reviewers:
            bullets.append(f"{', '.join(head_reviewers)} reviewed the current head.")
        elif thumbs:
            bullets.append(f"👍 on the PR from {', '.join(thumbs)}.")
        if self.effective_policy is not None:
            for scope in self.effective_policy.scopes:
                if scope.path and scope.files:
                    bullets.append(
                        f"{len(scope.files)} of the {len(self.pr.files)} changed files are governed by `{scope.path}`."
                    )
        bullets.extend(str(issue) for issue in (self.reviewer_output.get("issues") or [])[:3])

        rows = [f"| {g.gate} | {'✓' if g.passed else '✗'} | {g.message} |" for g in self.gate_results if g]
        rows.append(
            f"| policy |  | `.stamphog/policy.yml` @ `{_head_commit_sha()[:7]}`"
            f" · reviewed head `{self.pr.head_sha[:7]}` |"
        )
        details = (
            "<details>\n<summary>Gate mechanics and policy version</summary>\n\n"
            "| Gate |  | Result |\n|---|---|---|\n" + "\n".join(rows) + "\n\n</details>"
        )

        parts = [part for part in (reasoning, "\n".join(f"- {b}" for b in bullets) if bullets else "") if part]
        parts.append(details)
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "pr_number": self.pr.number,
            "repo": self.pr.repo,
            "title": self.pr.title,
            "author": self.pr.author,
            "head_sha": self.pr.head_sha,
            "classification": {
                # .get() not [] — the bot-author REFUSE returns before _classify(),
                # so classification is empty {} on that path; --output-json must
                # still serialize cleanly rather than KeyError.
                "tier": self.classification.get("tier", ""),
                "t1_subclass": self.classification.get("t1_subclass", ""),
                "lines_total": self.pr.lines_total,
                "files_changed": len(self.pr.files),
                "breadth": self.classification.get("breadth", ""),
                "commit_type": self.classification.get("commit_type"),
                "deny_categories": self.classification.get("deny_categories", []),
                "title_scrutiny_flags": self.classification.get("title_scrutiny_flags", []),
                "safe_migration_files": self.classification.get("safe_migration_files", []),
                "ownership": self.classification.get("ownership", {}),
                "familiarity": familiarity_evidence(self.classification.get("familiarity")),
            },
            "gates": [
                {"gate": g.gate, "passed": g.passed, "message": g.message} for g in self.gate_results if g is not None
            ],
            "policy": {
                "commit_sha": _head_commit_sha(),
                "policy_file": ".stamphog/policy.yml",
                "scopes": (
                    [
                        {"path": s.path, "max_files": s.max_files, "files": len(s.files)}
                        for s in self.effective_policy.scopes
                    ]
                    if self.effective_policy
                    else []
                ),
                "invalid_folder_files": (
                    list(self.effective_policy.invalid_folder_files) if self.effective_policy else []
                ),
            },
            "reviewer": self.reviewer_output,
            "review_body": self._render_review_body(),
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
