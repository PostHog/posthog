#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "claude-agent-sdk==0.2.113",
#     "anthropic==0.80.0",
#     "posthoganalytics==7.20.4",
#     "pyyaml==6.0.3",
# ]
# ///
# ruff: noqa: T201
"""Offline PR review entrypoint. The hosted sandbox runs this instead of review_pr.py.

review_pr.py is the manual entrypoint. It fetches everything over the network
(`gh`, GraphQL, git) and posts the verdict. This script runs the SAME engine
(gates, tier classification, git-blame familiarity, the LLM reviewer with the
same prompt and version) against a LOCAL checkout, with NO GitHub access and NO
token. The server holds the token, assembles every GitHub-sourced value that the
engine needs from the API, and passes them in through a `--context` JSON file.
Only one value flows back out: the JSON on the last stdout line, which is the
same `to_dict()` contract that review_pr.py emits with `--output-json`.

This script drives review_pr.Pipeline's own steps (classify, gates, the LLM
review, to_dict), so both entrypoints share one implementation of the engine
logic. It replaces only the steps that touch the network with injected data:
- _fetch (gh) becomes a PRData built from the context.
- The context injects the two `gh` calls that review_pr.py makes inside gate and
  familiarity, which are the author-team membership lookup and the author's
  merged-PR set. Familiarity's blame math is mirrored here with the injected PR
  set (see _familiarity_offline), because Pipeline._compute_familiarity hardcodes
  the `gh` fetch that only the networked entrypoint can make.

The engine reads the trusted policy (`.stamphog/policy.yml`,
`.stamphog/review-guidance.md`) from the checkout at import time. The server
overwrites those paths in the checkout with the default-branch versions before
this script runs, so a PR head cannot substitute its own gate. The reviewer key
comes from the environment (ANTHROPIC_API_KEY).
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
from gates import POLICY, assign_tier
from github import (
    TRUSTED_REACTOR_BOTS,
    PRData,
    _git_diff_files,
    _normalize_discussion_for_prompt,
    _normalize_reviews_for_prompt,
    _prompt_worthy_author,
    _reaction_emoji,
    is_bot_author,
    pr_provenance,
)
from migration_risk import migration_check_pending
from policy import FamiliarityPolicy
from review_pr import REPO_ROOT, GateResult, Pipeline, flush_analytics
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

    File stats are recomputed locally with the exact function that review_pr.py
    uses (`git diff --numstat` over base...head), so PRData.files is identical to
    a networked run. The context's file list is only a fallback for an empty
    local diff, which happens when a sha failed to fetch. The context also
    carries reviews, top-level discussion comments, and head-commit check runs.
    Reviews and discussion are normalized with the same helpers that review_pr.py
    uses, and check runs are passed through raw the same way. The prerequisite
    gate therefore blocks on an active
    CHANGES_REQUESTED, the agent sees maintainer discussion, and the migration
    gate can see a passing "Migration risk" check. Inline review-thread comments
    (a GraphQL-only surface with thread-resolution state) are carried when the
    hosted context supplies "review_threads"; only UNRESOLVED threads flow into
    the prompt, since an unresolved inline "do not merge" is the blocker the
    reviewer must see, and resolved threads are noise. An absent key means an
    empty list, which is a clean no-op and never a crash. A local review_pr.py
    run does not pass the key.
    Reactions on those inline comments are not carried, so they default empty.
    """
    pr = context.get("pr") or {}
    user = pr.get("user") or {}
    base = pr.get("base") or {}
    base_sha = context.get("base_sha") or base.get("sha") or ""
    head_sha = context.get("head_sha") or (pr.get("head") or {}).get("sha") or ""
    # Both feed PRData.stacked (the stacked-PR prompt note). A lean context without them reads as
    # non-stacked, matching the Action's default.
    default_branch = (base.get("repo") or {}).get("default_branch") or "master"
    base_ref = base.get("ref") or default_branch

    files = _git_diff_files(base_sha, head_sha, REPO_ROOT)
    if not files:
        files = [_convert_api_file(f) for f in context.get("files") or []]

    # Drop only EMPTY COMMENTED reviews from the offline reviews. A bare COMMENTED top-level review
    # carries no readable body — yet _summarize_assurance would surface its author as a current-head
    # reviewer ("head_commented"), reading as independent assurance. Unseen feedback must reduce to "no
    # assurance," never a positive vouch. (Any inline feedback that review left still reaches the prompt
    # via review_comments below, so dropping the empty top-level state loses nothing the reviewer needs.)
    # A COMMENTED review WITH a body is different: that text is
    # a maintainer's visible feedback (possibly a comment-only "hold"), and dropping it would let
    # the reviewer approve without ever seeing it — it flows through, body and all.
    reviews = [
        r for r in (context.get("reviews") or []) if r.get("state") != "COMMENTED" or (r.get("body") or "").strip()
    ]

    # Trusted-bot reactions only. The offline path has no token for the org-membership check that
    # the networked reactor predicate performs, and the in-flight wait consumes only allowlisted bot
    # 👀 in any case, because the code never waits on human reactions. REST content values
    # lowercase-match the mapper.
    author_login = user.get("login") or ""
    pr_reactions = [
        {"user": login, "emoji": _reaction_emoji(r.get("content", "")), "created_at": r.get("created_at")}
        for r in context.get("pr_reactions") or []
        if (login := r.get("user") or "") and login.lower() in TRUSTED_REACTOR_BOTS and login != author_login
    ]

    # Flatten the injected inline review threads into the review_comments shape the reviewer prompt
    # consumes. Only UNRESOLVED threads reach the prompt (see _build_pr_data's docstring); the full
    # list stays in the context. Each comment passes the same author-trust gate as reviews and
    # discussion — an untrusted external commenter must not plant a fake maintainer hold, and
    # stamphog's own prior comments must not feed back as third-party claims. An absent key yields
    # an empty list, so a local review_pr.py run, which does not pass the key, is unaffected and the
    # prompt renders no inline-comments section.
    review_comments: list[dict] = []
    for thread in context.get("review_threads") or []:
        if thread.get("is_resolved"):
            continue
        for index, comment in enumerate(thread.get("comments") or []):
            if not _prompt_worthy_author(
                comment.get("author"), comment.get("author_association"), bool(comment.get("author_is_bot"))
            ):
                continue
            # Real reply ids aren't carried in the lean shape; a truthy placeholder on the replies
            # only marks reply-ness — the prompt's "(reply)" label and _summarize_assurance's
            # "count threads (in_reply_to_id is None), not comments" semantic both key off it.
            # Parity with the networked path (github.py): only the TRUE thread root (index 0) may
            # carry None. When a filter removes the root (untrusted author, or stamphog's own
            # finding), every survivor is a reply, so the thread contributes 0 to
            # unresolved_threads. The networked path behaves the same way, because its surviving
            # replies keep their real non-None replyTo ids.
            review_comments.append(
                {
                    "user": comment.get("author") or "ghost",
                    "body": comment.get("body", ""),
                    "path": thread.get("path", ""),
                    "line": thread.get("line"),
                    "in_reply_to_id": None if index == 0 else -1,
                    "is_resolved": False,
                    "is_outdated": bool(thread.get("is_outdated")),
                    "reactions": [],
                }
            )

    return PRData(
        number=int(pr.get("number") or 0),
        repo=context.get("repo") or "",
        title=pr.get("title") or "",
        state=pr.get("state") or "",
        draft=bool(pr.get("draft")),
        mergeable_state=pr.get("mergeable_state") or "unknown",
        author=user.get("login") or "",
        labels=[label.get("name", "") for label in pr.get("labels") or []],
        base_ref=base_ref,
        base_sha=base_sha,
        head_sha=head_sha,
        files=files,
        reviews=_normalize_reviews_for_prompt(reviews, head_sha),
        review_comments=review_comments,
        check_runs=context.get("check_runs") or [],
        author_is_bot=is_bot_author(user),
        pr_reactions=pr_reactions,
        body=pr.get("body") or "",
        discussion=_normalize_discussion_for_prompt(context.get("discussion") or []),
        default_branch=default_branch,
    )


def _apply_ownership_summary(pipeline: Pipeline, author_team_slugs: set[str]) -> None:
    """Mirror Pipeline._summarize_ownership with team membership injected instead of fetched.

    review_pr.py resolves membership with one `gh` call per owning team. The sandbox holds no
    token, so the server supplies every team that the author belongs to, and this function does the
    intersection.

    `author_on_owning_team` matters beyond the summary text. The reviewer prompt reads that key with
    a default of True, so an unset key tells the reviewer that the author owns the code, whoever
    opened the PR. An unresolvable lookup arrives as an empty set and yields "not on any owning
    team". review_pr.py fails in the same direction, and that direction is the safe one for a bot that
    approves.
    """
    cl = pipeline.classification
    ownership = cl.get("ownership", {})
    individuals = ownership.get("individuals", [])
    teams = ownership.get("teams", [])
    if ownership.get("team_count", 0) == 0 and not individuals:
        cl["ownership_summary"] = "no owned paths touched"
        return

    author = pipeline.pr.author
    author_teams = [team for team in teams if team.split("/")[-1] in author_team_slugs]

    parts = []
    if teams:
        parts.append(f"touches {', '.join(teams)}")
    if individuals:
        # Individuals never enter the membership check. The author either is one of them or is
        # not.
        suffix = f" (author {author} is one of them)" if f"@{author}" in individuals else ""
        parts.append(f"individually owned by {', '.join(individuals)}{suffix}")
    if author_teams:
        parts.append(f"author {author} is on {', '.join(author_teams)}")
    elif teams:
        parts.append(f"author {author} is not on any owning team")
    if ownership.get("cross_team"):
        parts.append("cross-team change")

    cl["ownership_summary"] = "; ".join(parts)
    cl["author_on_owning_team"] = bool(author_teams)


def _run_gates_offline(pipeline: Pipeline, author_team_slugs: set[str]) -> None:
    """Run the four deterministic gate checks, the same ones that _run_gates runs.

    Mirrors Pipeline._run_gates, and replaces _summarize_ownership's `gh` membership lookup with the
    server-injected team set (see _apply_ownership_summary).
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

    _apply_ownership_summary(pipeline, author_team_slugs)


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
    prior PRs, previously-modified files, banding) is the engine's own bounded
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
    exactly as a failed `gh` call would in review_pr.py — a one-way ratchet.
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


def _blocked_only_by_pending_migration_check(pipeline: Pipeline) -> bool:
    """True when only the unfinished migration analyzer keeps this PR from a review.

    `Pipeline._only_pending_migration_check` cannot answer this. It disqualifies the PR on any
    failing gate other than the deny-list, and a migrations deny always pulls the tier gate down to
    T2-never as well. That method therefore returns False for every migration PR that it exists to
    catch.

    This function derives the tier again with the migrations deny removed, rather than special-casing
    the gate. A PR that is T2 for another reason (breadth, size, a second deny) therefore stays
    refused, and does not wait for a check that cannot change the outcome.
    """
    pr = pipeline.pr
    cl = pipeline.classification
    if cl.get("deny_categories") != ["migrations"]:
        return False
    if not migration_check_pending(pr.check_runs, pr.file_paths):
        return False
    if any(not gate.passed and gate.gate not in ("deny-list", "tier") for gate in pipeline.gate_results):
        return False
    tier_without_migrations = assign_tier(
        deny_categories=[],
        allow_listed_only=bool(cl.get("allow_listed_only")),
        is_test_only=bool(cl.get("is_test_only")),
        has_new_files=pr.has_new_files,
        lines_total=pr.lines_total,
        files_changed=len(pr.files),
        breadth=cl.get("breadth", ""),
        commit_type=cl.get("commit_type"),
    )
    return tier_without_migrations != "T2-never"


def run(context: dict) -> dict:
    """Run the full offline review and return the to_dict() contract."""
    # The hosted server sets self_driving_review only for PRs it verified came from a self-driving
    # Inbox implementation run. Action contexts never carry it, so bot authors are refused as before.
    # head_checkout: the sandbox clones and checks out the PR head before this runs (see the server's
    # _clone_pr), so parent-PR symbols already resolve for stacked PRs and no worktree is needed.
    pipeline = Pipeline(
        0,
        context.get("repo") or "",
        self_driving=bool(context.get("self_driving_review")),
        review_trigger=str(context.get("review_trigger") or ""),
        head_checkout=True,
    )
    pipeline.pr = _build_pr_data(context)
    # Reads commit trailers with `git log base..head` against the checkout, so it needs no token,
    # and it behaves here exactly as it does on a networked run. Without this call, the
    # agent-authorship evidence and the stamphog_review_completed provenance properties are null for
    # every hosted review.
    pipeline.provenance = pr_provenance(pipeline.pr.base_sha, pipeline.pr.head_sha, REPO_ROOT)

    if pipeline.pr.author_is_bot and not pipeline.self_driving:
        pipeline._refuse_bot_author()
        return pipeline.to_dict()

    try:
        pipeline._classify()
        _run_gates_offline(pipeline, {str(slug) for slug in context.get("author_team_slugs") or []})
        gate_verdict = pipeline._gate_verdict()

        # A `Migration risk` check that has not reported yet is a race with CI, and not a judgment
        # on the PR. The deny-list matched only because the engine cannot yet tell a safe migration
        # from a risky one. The verdict is WAIT rather than REFUSE because the hosted runtime routes
        # every refusal to a ReviewHog handoff and strips the trigger label. A refusal would
        # therefore escalate a transient check to a second review agent, and force the author to
        # re-request the review that it displaced.
        if _blocked_only_by_pending_migration_check(pipeline):
            pipeline.final_verdict = "WAIT"
            pipeline.reviewer_output = {
                "verdict": "WAIT",
                "reasoning": (
                    "The `Migration risk` check has not finished for this commit, so stamphog cannot "
                    "tell a safe migration from a risky one yet. The review runs again on the next "
                    "push, or you can re-request it once the check reports."
                ),
                "risk": "unknown",
                "issues": [],
            }
            pipeline._capture_review_completed(gate_verdict, "PENDING-MIGRATION-CHECK")
            return pipeline.to_dict()

        # Mirror review_pr.py's in-flight reviewer-bot handling, minus the wait: there is no token in
        # the sandbox to poll with, and the SERVER already waited out the race (workflow bot-wait
        # loop) and refreshed this snapshot before provisioning. Bots still showing fresh 👀 here
        # mean the server's budget expired — WAIT, never approve over an unfinished review. Gate
        # denials skip the check, same as review_pr.py: a refusal can't approve over anything.
        if gate_verdict != "DENIED" and (in_flight := pipeline._in_flight_bot_reviewers()):
            bot_list = ", ".join(f"@{b}" for b in in_flight)
            pipeline.final_verdict = "WAIT"
            pipeline.reviewer_output = {
                "verdict": "WAIT",
                "reasoning": (
                    f"{bot_list} still {'have' if len(in_flight) > 1 else 'has'} a review in flight (👀) — "
                    "not approving over an unfinished review. The review re-runs on the next push, or "
                    "re-request one once the reviewer finishes."
                ),
                "risk": "unknown",
                "issues": [],
            }
            return pipeline.to_dict()

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

    # Flush BEFORE the final line: batched capture events are dropped at process exit otherwise,
    # and any client noise the flush prints must stay above the machine-readable line.
    flush_analytics()

    # The single machine-readable line the server parses — always last on stdout.
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
