"""Tell another product whether stamphog's deterministic gates send one PR head to a person.

PostHog Review asks this before it starts an automatic review, to choose how deep that review goes.
The check reads the PR from GitHub at the head it is asked about and runs the engine's gate-only
pre-check on it (``run_engine_pregate``), outside any review run. It writes nothing to GitHub, creates
no run, starts no review and emits no analytics event.

The pre-check runs as if every prerequisite passes (not a draft, no merge conflict, no requested
changes), because the author or a reviewer clears those. The answer maps its finality onto three values:

- ``needs_human=True``: the pre-check is final, its verdict is REFUSED, and a size, deny-list or tier
  gate failed. No stamphog review can approve that head.
- ``needs_human=False``: the pre-check is final with none of those gates failed (a WAIT for a
  pending attestation), or every gate passed and no input the pre-check cannot read could add a
  failure.
- None: the check cannot tell. Every input the pre-check cannot trust, a pre-check that is not
  final for any reason other than "no gate failed", a bot author that the engine refuses without
  running the gates, and every error give None.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import structlog

from products.stamphog.backend.facade.contracts import ApprovalGateCheck
from products.stamphog.backend.logic.attestation_pins import get_check_runs_with_pins
from products.stamphog.backend.logic.bot_admission import admitted_bot_author
from products.stamphog.backend.logic.engine_pregate import (
    PregateOutcome,
    engine_default_policy_text,
    engine_gate_inputs,
    fetch_folder_policy_files,
    pregate_skip_reason,
    run_engine_pregate,
)
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.installations import reviewable_repo_config
from products.stamphog.backend.logic.reviewer import build_reviewer_invocation
from products.stamphog.backend.temporal.constants import (
    STAMPHOG_OPTIONAL_POLICY_PATHS,
    STAMPHOG_POLICY_ENTRYPOINT,
    STAMPHOG_POLICY_PATHS,
    STAMPHOG_SANDBOX_CONTEXT_PATH,
    STAMPHOG_SANDBOX_ENGINE_DIR,
)

logger = structlog.get_logger(__name__)

# The engine's names for the gates that refuse a PR for what it changes.
_HUMAN_GATES = frozenset({"size", "deny-list", "tier"})
# The not_final_reason the engine gives when no gate failed (`_not_final_reason` in review_local.py).
_NO_FAILING_GATE = "no_failing_gate"
# The policy key that exempts a deny category's owning teams. The `extend_exempt_author_teams` overlay key contains it.
_EXEMPT_TEAMS_KEY = "exempt_author_teams"
_READ_WORKERS = 8


class _Unknown(Exception):
    """The check cannot tell. ``reason`` names why, for the log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _policy_may_exempt_teams(policy_files: dict[str, str]) -> bool:
    """False only when neither the engine's default policy nor the repository's policy.yml names a team exemption.

    A plain text match, so a YAML comment that names the key counts too. That costs an answer, never a wrong one.
    """
    texts = (engine_default_policy_text(), policy_files.get(STAMPHOG_POLICY_ENTRYPOINT, ""))
    return any(_EXEMPT_TEAMS_KEY in text for text in texts)


def check_approval_gates(*, team_id: int, repository: str, pr_number: int, head_sha: str) -> ApprovalGateCheck | None:
    """Whether stamphog's gates send this PR head to a person, or None when that is unknown. Never raises."""
    ids = {"team_id": team_id, "repository": repository, "pr_number": pr_number}
    try:
        return _check_approval_gates(team_id=team_id, repository=repository, pr_number=pr_number, head_sha=head_sha)
    except _Unknown as unknown:
        logger.info("stamphog_approval_gate_check_unknown", reason=unknown.reason, **ids)
    except Exception:
        logger.warning("stamphog_approval_gate_check_failed", exc_info=True, **ids)
    return None


def _check_approval_gates(*, team_id: int, repository: str, pr_number: int, head_sha: str) -> ApprovalGateCheck:
    repo_config = reviewable_repo_config(team_id, repository)
    if repo_config is None:
        raise _Unknown("no_reviewable_repo_config")
    repo = repo_config.repository
    client = StamphogGitHubClient(repo_config.installation_id)
    # Mint the installation token once up front. On a cold cache every pool thread would mint its own.
    client.installation_token()
    executor = ThreadPoolExecutor(max_workers=_READ_WORKERS, thread_name_prefix="stamphog-gate-check")
    try:

        def submit(fetch: Callable[..., Any], *args: Any) -> Future[Any]:
            # A pool thread starts with an empty context. Each read runs in its own copy of the caller's,
            # so its log lines keep the caller's bound fields, and one copy never runs in two threads.
            return executor.submit(contextvars.copy_context().run, fetch, *args)

        pr_future = submit(client.get_pr, repo, pr_number)
        files_future = submit(client.get_pr_files, repo, pr_number)
        check_runs_future = submit(get_check_runs_with_pins, client, repo, head_sha)
        policy_futures = {
            path: submit(client.get_default_branch_file, repo, path)
            for path in (*STAMPHOG_POLICY_PATHS, *STAMPHOG_OPTIONAL_POLICY_PATHS)
        }

        pr = pr_future.result()
        files = files_future.result()
        if skip_reason := pregate_skip_reason(pr, files, head_sha):
            raise _Unknown(skip_reason)
        author = (pr.get("user") or {}).get("login") or ""
        if not author:
            raise _Unknown("no_author")
        # The review passes the same login, so the engine runs every gate for a bot the policy admits.
        admission = admitted_bot_author(repo_config, pr)
        base_sha = (pr.get("base") or {}).get("sha") or ""
        # An object-form attestation proves one merge base, so a deny lift needs the PR's own.
        merge_base_future = submit(client.get_merge_base_sha, repo, base_sha, head_sha)
        author_teams_future = submit(client.find_user_team_slugs, repo.split("/")[0], author)
        folder_policy_future = submit(fetch_folder_policy_files, client, repo, head_sha, files)

        policy_files = {path: text for path, future in policy_futures.items() if (text := future.result()) is not None}
        author_team_slugs = author_teams_future.result()
        if author_team_slugs is None:
            # A deny category can exempt the teams that own it, and a failed lookup reads as "on no team", which
            # denies an exempt author. Without an exemption in the policy, the teams decide no gate.
            if _policy_may_exempt_teams(policy_files):
                raise _Unknown("author_teams_unknown")
            author_team_slugs = []
        # Without the folder files the size gate budgets differently from the sandbox.
        folder_policy_files = folder_policy_future.result()
        if folder_policy_files is None:
            raise _Unknown("folder_policy_files_unknown")
        invocation = build_reviewer_invocation(
            # No prerequisite input fails, as the module docstring says. A failing prerequisite would also make the
            # engine's refusal final over a deny that a pending attestation can still lift (`_denial_is_final` in
            # review_local.py).
            pr={**pr, "draft": False, "mergeable_state": "clean"},
            files=files,
            reviews=[],
            check_runs=check_runs_future.result(),
            author_team_slugs=author_team_slugs,
            base_sha=base_sha,
            merge_base_sha=merge_base_future.result(),
            head_sha=head_sha,
            repo=repo,
            # No gate reads these. They feed the reviewer prompt, the in-flight bot wait and the
            # analytics event, which a gate-only run does not reach.
            discussion=[],
            review_threads=[],
            pr_reactions=[],
            author_pr_numbers=[],
            familiarity_facts=None,
            commit_messages=None,
            # The pre-check only reads the context. The command these build is never run.
            engine_dir=STAMPHOG_SANDBOX_ENGINE_DIR,
            context_path=STAMPHOG_SANDBOX_CONTEXT_PATH,
            admitted_bot=admission["login"] if admission else "",
        )
    finally:
        # A failed read raises out of its result() above. The other reads are abandoned rather than awaited.
        executor.shutdown(wait=False, cancel_futures=True)

    context, tree_files = engine_gate_inputs(
        context_json=invocation.context_json,
        repository=repo,
        policy_files=policy_files,
        folder_policy_files=folder_policy_files,
    )
    # An empty environment keeps the engine from emitting its review event for a check that posts nothing.
    outcome = run_engine_pregate(context, tree_files, environment={})
    return _gate_check(outcome)


def _gate_check(outcome: PregateOutcome) -> ApprovalGateCheck:
    if not outcome.final:
        if outcome.not_final_reason == _NO_FAILING_GATE:
            return ApprovalGateCheck(needs_human=False, failed_gates=())
        raise _Unknown(f"not_final:{outcome.not_final_reason or 'unknown'}")
    result = outcome.result or {}
    verdict = result.get("final_verdict")
    # The engine's final WAIT: a pending attestation may still lift the deny, so the head can pass.
    if verdict == "WAIT":
        return ApprovalGateCheck(needs_human=False, failed_gates=())
    if verdict != "REFUSED":
        raise _Unknown(f"final_verdict:{verdict}")
    # The bot-author refusal runs no gate. Stamphog still reviews some of these PRs with every gate, under the
    # self-driving inbox carve-out, which this check does not resolve.
    if not result.get("gates"):
        raise _Unknown("bot_author")
    failed_gates = tuple(
        gate["gate"]
        for gate in result.get("gates") or []
        if isinstance(gate, dict) and gate.get("passed") is False and gate.get("gate") in _HUMAN_GATES
    )
    return ApprovalGateCheck(needs_human=bool(failed_gates), failed_gates=failed_gates)
