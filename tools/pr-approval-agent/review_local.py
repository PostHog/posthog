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
"""Offline PR review entrypoint — the sandbox runs this instead of review_pr.py.

review_pr.py fetches everything over the network (`gh`, GraphQL, git) and posts
the verdict. This script runs the SAME engine (gates, tier classification,
git-blame familiarity, the LLM reviewer with the same prompt/version) against a
LOCAL checkout, with NO GitHub access and NO token. All GitHub-sourced data the
engine needs is handed in via a `--context` JSON file that the server (which
holds the token) assembles from the API; the only thing that flows back out is
the JSON on the last stdout line — the same `to_dict()` contract review_pr.py
emits with `--output-json`.

Reuse: it drives review_pr.Pipeline's own steps (classify, gates, the LLM
review, to_dict) so the engine logic stays byte-identical to the Action. Only
the two steps that touch the network are replaced with injected data:
- _fetch (gh) → a PRData built from the context.
- the two `gh` calls the Action makes inside gate/familiarity — the author-team
  membership lookup (advisory ownership enrichment) and the author's merged-PR
  set — are skipped / injected. Familiarity's blame math is mirrored here with
  the injected PR set (see _familiarity_offline) because Pipeline._compute_familiarity
  hardcodes the `gh` fetch and must not be modified (the Action stays additive-only).

Trusted policy (`.stamphog/policy.yml`, `.stamphog/review-guidance.md`) is read
by the engine from the checkout at import time; the server overwrites those paths
in the checkout with the default-branch versions before this runs, so a PR head
can't substitute its own gate. The reviewer key comes from the environment
(ANTHROPIC_API_KEY), same as before.
"""

import os
import json
import time
import argparse
from pathlib import Path

from familiarity import (
    AuthorFamiliarity,
    _band,
    _blame_overlap,
    _files_previously_modified,
    _merge_base,
    _parse_diff,
    _prior_prs_in_paths,
    _read_diff,
    _select_considered_files,
)
from gates import POLICY
from github import PRData, _git_diff_files, is_bot_author
from policy import FamiliarityPolicy
from review_pr import REPO_ROOT, GateResult, Pipeline
from version import STAMPHOG_VERSION


def _api_file_status(status: str) -> str:
    """Map a get_pr_files status string onto the single-letter code the engine expects.

    github._git_diff_files uses git's --name-status letters (A/M/D/R/C); the
    GitHub files API spells them out. Only used on the fallback path when the
    local `git diff` produced nothing.
    """
    return {
        "added": "A",
        "modified": "M",
        "removed": "D",
        "renamed": "R",
        "copied": "C",
        "changed": "M",
    }.get(status, "M")


def _convert_api_file(f: dict) -> dict:
    """Convert a get_pr_files object into github._git_diff_files' file dict shape."""
    additions = int(f.get("additions", 0) or 0)
    deletions = int(f.get("deletions", 0) or 0)
    # The files API omits an explicit binary flag; a changed file with no patch
    # and no line counts is binary (or too large for GitHub to inline).
    is_binary = f.get("patch") is None and additions == 0 and deletions == 0
    return {
        "filename": f.get("filename", ""),
        "additions": additions,
        "deletions": deletions,
        "binary": is_binary,
        "status": _api_file_status(str(f.get("status", "modified"))),
    }


def _build_pr_data(context: dict) -> PRData:
    """Build the engine's PRData from the injected context.

    File stats are recomputed locally with the exact function the Action uses
    (`git diff --numstat` over base...head) so PRData.files is identical to a
    real run; the context's file list is only a fallback if the local diff is
    empty (e.g. a sha failed to fetch). Reviews/comments/reactions/check-runs
    are metadata the slim context does not carry, so they default empty — the
    reviewer prompt renders their sections as "none", which is strictly a subset
    of what the Action shows, never a fabrication.
    """
    pr = context.get("pr") or {}
    user = pr.get("user") or {}
    base_sha = context.get("base_sha") or (pr.get("base") or {}).get("sha") or ""
    head_sha = context.get("head_sha") or (pr.get("head") or {}).get("sha") or ""

    files = _git_diff_files(base_sha, head_sha, REPO_ROOT)
    if not files:
        files = [_convert_api_file(f) for f in context.get("files") or []]

    return PRData(
        number=int(pr.get("number") or 0),
        repo=context.get("repo") or "",
        title=pr.get("title") or "",
        state=pr.get("state") or "",
        draft=bool(pr.get("draft")),
        mergeable_state=pr.get("mergeable_state") or "unknown",
        author=user.get("login") or "",
        labels=[label.get("name", "") for label in pr.get("labels") or []],
        base_sha=base_sha,
        head_sha=head_sha,
        files=files,
        reviews=[],
        review_comments=[],
        check_runs=[],
        author_is_bot=is_bot_author(user),
        pr_reactions=[],
        body=pr.get("body") or "",
        discussion=[],
    )


def _run_gates_offline(pipeline: Pipeline) -> None:
    """Run the four deterministic gate checks — the same ones _run_gates runs.

    Mirrors Pipeline._run_gates minus its `_summarize_ownership` call, which
    shells out to `gh` for author-team membership. Membership is advisory
    reviewer context (never a gate), so it is simply omitted here; the ownership
    teams themselves are still resolved locally from the checkout.
    """
    gates = [
        ("prerequisites", pipeline._check_prerequisites),
        ("deny-list", pipeline._check_deny_list),
        ("size", pipeline._check_size),
        ("tier", pipeline._check_tier),
    ]
    for name, check in gates:
        passed, message = check()
        pipeline.gate_results.append(GateResult(name, passed, message))

    ownership = pipeline.classification.get("ownership", {})
    if ownership.get("team_count", 0) == 0:
        pipeline.classification["ownership_summary"] = "no owned paths touched"
    else:
        pipeline.classification["ownership_summary"] = f"touches {', '.join(ownership.get('teams', []))}"


def _familiarity_offline(
    author_prs: set[int],
    diff_path: Path,
    base_sha: str,
    head_sha: str,
    thresholds: FamiliarityPolicy,
    *,
    now: float | None = None,
) -> AuthorFamiliarity:
    """Mirror of familiarity.compute_familiarity with the author-PR set injected.

    compute_familiarity fetches the author's merged-PR numbers with one `gh`
    call, which is impossible in the tokenless sandbox — the server fetches them
    and hands them in via the context instead. Everything else (blame overlap,
    prior PRs, previously-modified files, banding) is the Action's own bounded
    git logic, called here unchanged.
    """
    now = time.time() if now is None else now
    file_diffs = _parse_diff(_read_diff(diff_path))
    considered, capped = _select_considered_files(file_diffs)
    considered_paths = [f.path for f in considered if f.path]

    blame_sha = _merge_base(base_sha, head_sha, REPO_ROOT)
    if blame_sha is not None:
        owned, total, top_authors = _blame_overlap(considered, blame_sha, author_prs, REPO_ROOT)
    else:
        owned, total, top_authors = 0, 0, ()
    blame_overlap_pct = (100.0 * owned / total) if total else 0.0

    prior_prs, days_since = _prior_prs_in_paths(considered_paths, author_prs, REPO_ROOT, now)
    files_prev_count, files_total = _files_previously_modified(considered, author_prs, REPO_ROOT)
    band = _band(blame_overlap_pct, prior_prs, days_since, thresholds)

    return AuthorFamiliarity(
        band=band,
        blame_overlap_pct=blame_overlap_pct,
        modified_lines_owned=owned,
        modified_lines_total=total,
        prior_prs_in_paths=prior_prs,
        days_since_last_touch=days_since,
        files_prev_count=files_prev_count,
        files_total=files_total,
        capped=capped,
        top_prior_authors=top_authors,
    )


def _attach_familiarity(pipeline: Pipeline, context: dict) -> None:
    """Attach the author-familiarity signal for the T1-agent path only.

    Same gating as Pipeline._maybe_compute_familiarity (T0 skips the LLM, T2 is a
    deny, so neither benefits). Absent injected PR numbers leaves the signal None,
    exactly as a failed `gh` call would in the Action — a one-way ratchet.
    """
    if pipeline.classification.get("tier") != "T1-agent":
        return
    raw_prs = context.get("author_pr_numbers")
    if not raw_prs:
        return
    author_prs = {int(n) for n in raw_prs}
    diff_path = pipeline._ensure_diff_path()
    try:
        pipeline.classification["familiarity"] = _familiarity_offline(
            author_prs, diff_path, pipeline.pr.base_sha, pipeline.pr.head_sha, POLICY.familiarity
        )
    except Exception as exc:
        print(f"warning: familiarity computation failed ({exc}); continuing without the signal")


def run(context: dict) -> dict:
    """Run the full offline review and return the to_dict() contract."""
    pipeline = Pipeline(0, context.get("repo") or "")
    pipeline.pr = _build_pr_data(context)

    if pipeline.pr.author_is_bot:
        pipeline._refuse_bot_author()
        return pipeline.to_dict()

    try:
        pipeline._classify()
        _run_gates_offline(pipeline)
        gate_verdict = pipeline._gate_verdict()
        _attach_familiarity(pipeline, context)
        pipeline._llm_review(gate_verdict)
    finally:
        if pipeline._diff_path is not None:
            pipeline._diff_path.unlink(missing_ok=True)

    return pipeline.to_dict()


def _escalate_result(context: dict, exc: Exception) -> dict:
    """A minimal, parseable escalate outcome for an unexpected internal failure.

    Keeps the last-line contract intact so the server parses a defined verdict
    (escalate, never a silent approval) rather than choking on a stack trace.
    """
    pr = context.get("pr") or {}
    return {
        "stamphog_version": STAMPHOG_VERSION,
        "pr_number": pr.get("number"),
        "repo": context.get("repo") or "",
        "classification": {},
        "gates": [],
        "policy": {},
        "reviewer": {
            "verdict": "ESCALATE",
            "reasoning": "The review agent could not complete its analysis — escalating for a human.",
            "risk": "high",
            "issues": [str(exc)],
        },
        "review_body": None,
        "final_verdict": "ESCALATE",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline PR review (sandbox entrypoint)")
    parser.add_argument("--context", required=True, help="Path to the review context JSON")
    parser.add_argument("--repo-dir", default=None, help="Checkout directory (defaults to cwd)")
    args = parser.parse_args()

    if args.repo_dir:
        os.chdir(args.repo_dir)

    context = json.loads(Path(args.context).read_text())
    try:
        result = run(context)
    except Exception as exc:  # never let a crash become a silent non-verdict
        result = _escalate_result(context, exc)

    # The single machine-readable line the server parses — always last on stdout.
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
