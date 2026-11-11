"""A stable hash of the inputs a review decided on.

A silent run keeps its verdict off the PR. When somebody asks for a visible review of the same head
later, stamphog publishes that stored verdict only if this hash still matches the inputs read again
from GitHub. Any doubt makes the hashes differ, and a differing hash means a fresh review.
"""

from __future__ import annotations

import json
import hashlib
import functools
from collections.abc import Collection
from typing import Any

from products.stamphog.backend.logic.engine_pregate import engine_source_files, owners_package_files
from products.stamphog.backend.temporal.constants import STAMPHOG_TRUSTED_REACTOR_BOTS

DECISION_FINGERPRINT_OUTPUT_KEY = "decision_fingerprint"

# On a visible request's run: the silent run whose withheld verdict it publishes when the inputs
# still match, and, once it did, the run it took the verdict from.
WITHHELD_RUN_OUTPUT_KEY = "withheld_run_id"
REUSED_FROM_RUN_OUTPUT_KEY = "reused_from_run_id"

# Mirrors CHECK_NAME in packages/pr-approval-agent/migration_risk.py. The engine reads no other
# check run, so a CI check that finishes between two reads must not count as a changed input.
MIGRATION_RISK_CHECK_NAME = "Migration risk"

# PR fields left out of the hash because they move without changing what the engine decides on:
# - updated_at moves on every comment, label, review and reviewer request.
# - mergeable, rebaseable and merge_commit_sha are computed lazily by GitHub and flip between reads.
#   mergeable_state is the same, so only "dirty" (a merge conflict, the one state the engine reads)
#   goes into the hash.
# - requested_reviewers and requested_teams are written by stamphog's own reviewer routing.
# - assignee, assignees and auto_merge decide who merges and when, and the engine reads none of them.
# - comments and review_comments are counters. The discussion and the review threads carry the content.
# - labels are hashed by name without stamphog's own labels, because the trigger label is the visible
#   request itself and the routing fork labels are stamphog's own writes.
# - The base and head repository objects keep only full_name, default_branch and fork. The rest are
#   repository statistics (pushed_at, stargazers_count, ...) that move with every push to any branch.
# Besides the context, the hash covers the engine itself (engine_package_digest): the repo's policy
# files only override the shipped defaults, and the engine's code and prompts decide as much as the
# inputs do. A deploy that changes any of them makes every stored verdict stale.
_PR_EXCLUDED_KEYS = frozenset(
    {
        "updated_at",
        "mergeable",
        "mergeable_state",
        "rebaseable",
        "merge_commit_sha",
        "requested_reviewers",
        "requested_teams",
        "assignee",
        "assignees",
        "auto_merge",
        "comments",
        "review_comments",
        "labels",
    }
)
_REPO_KEPT_KEYS = ("full_name", "default_branch", "fork")
# A comment edit changes its body, so updated_at adds nothing. Reactions on a comment never reach the engine.
_DISCUSSION_EXCLUDED_KEYS = frozenset({"updated_at", "reactions"})


def _canonical_repo(repo: Any) -> Any:
    if not isinstance(repo, dict):
        return repo
    return {key: repo.get(key) for key in _REPO_KEPT_KEYS}


def _canonical_pr(pr: dict, ignored_labels: Collection[str]) -> dict:
    canonical = {key: value for key, value in pr.items() if key not in _PR_EXCLUDED_KEYS}
    canonical["labels"] = sorted(
        name
        for label in pr.get("labels") or []
        if isinstance(label, dict) and (name := label.get("name")) and name not in ignored_labels
    )
    canonical["merge_conflict"] = pr.get("mergeable_state") == "dirty"
    for side in ("base", "head"):
        ref = pr.get(side)
        if isinstance(ref, dict):
            canonical[side] = {**ref, "repo": _canonical_repo(ref.get("repo"))}
    return canonical


@functools.cache
def engine_package_digest() -> str:
    """A sha256 over the engine modules, its shipped default policy and the owners package. The files
    only change with a deploy, so one read per process is enough."""
    files = {**engine_source_files(), **{f"owners_yaml/{name}": text for name, text in owners_package_files().items()}}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def decision_fingerprint(
    context: dict[str, Any], *, head_sha: str, ignored_labels: Collection[str], engine_digest: str
) -> str:
    """Hash the engine inputs in ``context``, which has the shape of a run's stored output.

    Only the keys the engine context is built from count. Run bookkeeping (timings, ids, the bot
    wait) never enters. The run's provenance (``review_trigger``, ``self_driving_review``) is left
    out too. Both sides of a comparison belong to the same run, and a visible request differs from
    the silent trigger on purpose: the trigger only tells the reviewer why it was asked.
    """
    pr = context.get("pr") or {}
    canonical = {
        "engine": engine_digest,
        "head_sha": head_sha,
        "pr": _canonical_pr(pr, ignored_labels),
        "files": context.get("files") or [],
        "reviews": context.get("reviews") or [],
        "discussion": [
            {key: value for key, value in comment.items() if key not in _DISCUSSION_EXCLUDED_KEYS}
            for comment in context.get("discussion") or []
            if isinstance(comment, dict)
        ],
        "review_threads": context.get("review_threads") or [],
        "check_runs": [
            check_run
            for check_run in context.get("check_runs") or []
            if isinstance(check_run, dict) and check_run.get("name") == MIGRATION_RISK_CHECK_NAME
        ],
        # The engine keeps only the trusted reviewer bots' reactions, so nobody else's reaction is an input.
        "pr_reactions": [
            reaction
            for reaction in context.get("pr_reactions") or []
            if isinstance(reaction, dict) and (reaction.get("user") or "").lower() in STAMPHOG_TRUSTED_REACTOR_BOTS
        ],
        "review_evidence": context.get("review_evidence") or [],
        # GitHub's search answers in no stable order, and the engine uses these as a set.
        "author_pr_numbers": sorted(context.get("author_pr_numbers") or []),
        "author_team_slugs": sorted(context.get("author_team_slugs") or []),
        "familiarity_facts": context.get("familiarity_facts"),
        "merge_base_sha": context.get("merge_base_sha"),
        "commit_messages": context.get("commit_messages"),
        "policy_files": context.get("policy_files") or {},
        "folder_policy_files": context.get("folder_policy_files"),
    }
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
