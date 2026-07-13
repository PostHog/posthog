"""Full-chain, single-process testbed for stamphog. Run it, watch the whole chain fire.

Signed GitHub webhook  ->  real view + HMAC verify
  ->  real Celery task (eager)     ->  upsert PR, supersede, queue ReviewRun
  ->  inline "workflow"            ->  real fetch/run/post activities (Temporal faked)
  ->  merged-PR capture            ->  audience_key stamping
  ->  real daily-digest tasks      ->  channel auto-provision + Slack post

Only two things are faked, each at its natural seam:
  * GitHub — at the egress transport (``github_request``), see fake_github.py
  * Slack  — at ``SlackIntegration``, see fake_slack.py
Everything else (webhook view, task, activities, ORM, digest logic) is the real code.

DB model — see README.md for the full reasoning. In short: stamphog models live on a separate
product DB. Three real-world quirks have to be reconciled to run this on a laptop:
  1. The task's ``transaction.atomic()`` targets the *default* DB, but the product-DB
     ``select_for_update`` needs an ambient transaction on the *stamphog* connection.
  2. Product reads route to the reader connection outside tests, so an in-flight write is
     invisible to a subsequent read on a different connection.
  3. Eager Celery closes DB connections after each task; a transaction left open across a
     task (autocommit off) is rolled back on close, losing the rows.
The harness reconciles all three the way the pytest product-DB suite does: it routes product
reads to the writer, replaces the task module's ``transaction`` with a shim whose ``atomic()``
targets the stamphog writer (so each task commits its own rows before Celery's cleanup) and
whose ``on_commit`` runs inline, and drives the activities in-thread via the plain sync body
under ``@asyncify`` so they share the one connection.

Invocation (from repo root):
    flox activate -- bash -c 'DEBUG=1 ./manage.py shell < products/stamphog/backend/dev/harness.py'

Env knobs:
    HARNESS_TEAM_ID=<id>   reuse an existing dev team instead of creating one
    SANDBOX_MODE=stub|real stub (default) injects a scripted engine verdict; real runs docker
    KEEP=1                 commit + keep the harness rows instead of rolling them back
"""

from __future__ import annotations

import os
import json
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from unittest.mock import patch

from django.db import transaction
from django.test import Client, override_settings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.models.integration import Integration
from posthog.models.organization import Organization

from products.stamphog.backend.dev import fake_github, payloads
from products.stamphog.backend.dev.fake_slack import FakeSlackIntegration
from products.stamphog.backend.facade.enums import ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.models import DigestChannel, DigestRun, PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tasks.digest import send_daily_digests
from products.stamphog.backend.temporal.activities import (
    MarkReviewFailedInput,
    StamphogReviewInput,
    fetch_review_context,
    mark_review_failed,
    post_verdict,
    run_review_in_sandbox,
)

# --- Scenario constants ---
WEBHOOK_PATH = "/webhooks/stamphog/github"
WEBHOOK_SECRET = "harness-webhook-secret"
REPO = "harness/widgets"
INSTALLATION_ID = "harness-inst-1"
BASE_SHA = "base000"
WRITER_DB = "stamphog_db_writer"


# --- Fake sandbox (stub mode) ---
@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None


def _approved_engine_output() -> str:
    """A realistic ``review_pr`` ``to_dict()`` payload: gates pass, final verdict APPROVED.

    Emitted as the reviewer's last stdout line (uv/SDK noise can precede it), which is exactly
    what ``parse_reviewer_output`` scans for.
    """
    payload = {
        "final_verdict": "APPROVED",
        "reviewer": {"reasoning": "Small, well-tested change. No policy concerns.", "issues": []},
        "gates": [
            {"name": "size", "passed": True},
            {"name": "deny_list", "passed": True},
            {"name": "tier", "passed": True},
            {"name": "prerequisites", "passed": True},
        ],
        "classification": {"tier": "low_risk", "reason": "docs + small logic change"},
        "policy": {"version": "1"},
        "review_body": "Approved by stamphog. All deterministic gates passed; change is low risk.",
        "stamphog_version": "harness-1.0.0",
    }
    return "uv run: resolved 1 package\n" + json.dumps(payload)


def _make_fake_sandbox_class(engine_output: str, exec_log: list[str]) -> type:
    class _FakeSandbox:
        @classmethod
        def create(cls, config: Any) -> _FakeSandbox:
            return cls()

        def execute(self, command: str, timeout_seconds: int | None = None) -> FakeExecResult:
            exec_log.append(command)
            stdout = engine_output if "review_local.py" in command else ""
            return FakeExecResult(stdout=stdout, stderr="", exit_code=0)

        def write_file(self, path: str, payload: bytes) -> FakeExecResult:
            return FakeExecResult(stdout="", stderr="", exit_code=0)

        def destroy(self) -> None:
            return None

    return _FakeSandbox


# --- Trace printing ---
def _step(title: str) -> None:
    print("\n" + "=" * 78 + f"\n# {title}\n" + "=" * 78)  # noqa: T201 — dev harness prints a trace


def _log(msg: str) -> None:
    print(f"  · {msg}")  # noqa: T201 — dev harness prints a trace


def _check(label: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")  # noqa: T201 — dev harness prints a trace
    if not ok:
        raise AssertionError(label)


# --- Inline "workflow" replacing the Temporal client ---
def _run_activity(activity_fn: Any, arg: Any) -> Any:
    """Run a stamphog activity's plain sync body in-thread.

    The activities are ``@activity.defn`` over ``@asyncify`` — ``__wrapped__`` is the original
    sync function, callable directly so it shares the harness's DB connection + transaction
    (production drives the same body from a Temporal worker thread instead).
    """
    return activity_fn.__wrapped__(arg)


class _TxShim:
    """Drop-in for the ``transaction`` module reference inside ``tasks/tasks.py``.

    ``atomic()`` targets the stamphog writer so the task's ``select_for_update`` runs in a real
    product-DB transaction that commits within the task (surviving eager Celery's connection
    cleanup); ``on_commit`` runs inline so the inline "workflow" fires while the rows are visible.
    Scoped to the task module only — the global ``django.db.transaction`` is untouched.
    """

    def atomic(self, *args: Any, **kwargs: Any) -> Any:
        return transaction.atomic(using=WRITER_DB)

    def on_commit(self, func: Any, using: Any = None) -> None:
        func()


def _make_fake_workflow(state: dict[str, bool]) -> Any:
    """Mirror StamphogReviewWorkflow by driving the real activities in order.

    ``state["enabled"] = False`` leaves the run QUEUED (as if Temporal hadn't picked it up yet),
    which is what lets the next push demonstrate supersession.
    """

    def _fake_workflow(review_run_id: str, team_id: int) -> None:
        if not state["enabled"]:
            _log(f"workflow suppressed — run {review_run_id[:8]} left QUEUED")
            return
        inp = StamphogReviewInput(review_run_id=review_run_id, team_id=team_id)
        try:
            _run_activity(fetch_review_context, inp)
            _run_activity(run_review_in_sandbox, inp)
            _run_activity(post_verdict, inp)
        except Exception as e:  # noqa: BLE001 — mirror the workflow's failure path
            _log(f"workflow error, marking run failed: {e}")
            _run_activity(mark_review_failed, MarkReviewFailedInput(review_run_id, team_id, str(e)))

    return _fake_workflow


# --- Webhook POST ---
def _post_webhook(client: Client, payload: dict[str, Any]) -> int:
    body = payloads.encode(payload)
    signature = payloads.sign_payload(body, WEBHOOK_SECRET)
    delivery_id = str(uuid.uuid4())
    response = client.post(
        WEBHOOK_PATH,
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
        HTTP_X_GITHUB_EVENT="pull_request",
        HTTP_X_GITHUB_DELIVERY=delivery_id,
    )
    return response.status_code


# --- PR object + files served by the GitHub fake ---
def _pr_object(number: int, author: str, head_sha: str, title: str) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "body": "Adds a small helper and a test.",
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "user": {"login": author},
        "head": {"sha": head_sha, "ref": f"feat/pr-{number}"},
        "base": {"sha": BASE_SHA, "ref": "master"},
        "draft": False,
    }


def _pr_files() -> list[dict[str, Any]]:
    return [
        {"filename": "src/util.py", "status": "modified", "additions": 8, "deletions": 1, "patch": "@@ -1 +1 @@"},
        {"filename": "tests/test_util.py", "status": "added", "additions": 20, "deletions": 0, "patch": "@@ +1 @@"},
    ]


# --- Repo root + policy files ---
def _repo_root() -> Path:
    """Locate the repo root by walking up from the cwd until ``.stamphog/policy.yml`` appears.

    ``__file__`` is unreliable here — piped through ``manage.py shell`` the exec'd globals carry a
    venv path — so anchor on the cwd (the documented invocation runs from the repo root).
    """
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".stamphog" / "policy.yml").is_file():
            return candidate
    raise RuntimeError("could not locate repo root (.stamphog/policy.yml) — run from the repo root")


def _configure_github(recorder: fake_github.GitHubRecorder) -> None:
    """Load the real repo policy files the review + digest paths fetch from the default branch."""
    repo_root = _repo_root()
    recorder.policy_files = {
        ".stamphog/policy.yml": (repo_root / ".stamphog" / "policy.yml").read_text(),
        ".stamphog/review-guidance.md": (repo_root / ".stamphog" / "review-guidance.md").read_text(),
    }


# --- Team + integration setup ---
def _setup_team() -> tuple[int, int | None, Any]:
    """Return (team_id, integration_id, cleanup_org). Reuses HARNESS_TEAM_ID if set."""
    existing = os.environ.get("HARNESS_TEAM_ID")
    if existing:
        team_id = int(existing)
        org = None
        _log(f"reusing existing dev team id={team_id}")
    else:
        org, _, team = Organization.objects.bootstrap(user=None, name="stamphog-harness")
        team_id = team.id
        _log(f"created org 'stamphog-harness' + team id={team_id}")

    integration = Integration.objects.create(
        team_id=team_id,
        kind="slack",
        config={"authed_user": {"id": "U-harness"}, "scope": "channels:read"},
        sensitive_config={"access_token": "xoxb-harness-fake"},
    )
    _log(f"created slack Integration id={integration.id}")
    return team_id, integration.id, org


def _purge_orphan_harness_rows() -> None:
    """Delete leftover ``harness/`` rows from any team before we start.

    ``_resolve_repo_config`` is oldest-wins across teams by (installation_id, repository), so a
    stale config from a previously crashed run would hijack this run's webhooks onto a dead team.
    A clean slate guarantees the webhook resolves to *this* run's config.
    """
    teams = set(
        StamphogRepoConfig.objects.unscoped()
        .filter(repository__startswith="harness/")
        .values_list("team_id", flat=True)
    )
    if not teams:
        return
    for model in (DigestRun, ReviewRun, PullRequest, DigestChannel, StamphogRepoConfig):
        model.objects.unscoped().filter(team_id__in=teams).delete()
    _log(f"purged orphan harness rows from teams {sorted(teams)}")


def _run_steps(
    client: Client, team_id: int, recorder: fake_github.GitHubRecorder, workflow_state: dict[str, bool]
) -> None:
    """Steps 1-6 of the scenario."""
    _purge_orphan_harness_rows()

    # 1. Repo config (digest opted in).
    repo_config = StamphogRepoConfig.objects.for_team(team_id).create(
        team_id=team_id, repository=REPO, installation_id=INSTALLATION_ID, enabled=True, digest_enabled=True
    )
    _log(f"StamphogRepoConfig id={repo_config.id} repo={REPO} digest_enabled=True")

    # ---------------------------------------------------------------
    _step("STEP 2: PR #101 opened -> review -> APPROVE posted")
    author = "devex-dev"
    recorder.teams_by_login[author] = ["team-devex"]
    recorder.author_merged[(REPO, author)] = [50, 60]
    recorder.register_pr(REPO, 101, _pr_object(101, author, "sha101a", "Add util helper"), _pr_files())

    opened = payloads.build_pull_request_event(
        action="opened",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=101,
        title="Add util helper",
        body="Adds a small helper and a test.",
        author_login=author,
        head_sha="sha101a",
        head_ref="feat/pr-101",
        base_sha=BASE_SHA,
    )
    status = _post_webhook(client, opened)
    _check(f"webhook accepted (202), got {status}", status == 202)

    pr = PullRequest.objects.for_team(team_id).get(repo_config=repo_config, pr_number=101)
    run1 = ReviewRun.objects.for_team(team_id).filter(pull_request=pr).latest("created_at")
    _check("PullRequest #101 exists", pr is not None)
    _check(f"ReviewRun COMPLETED (got {run1.status})", run1.status == ReviewRunStatus.COMPLETED)
    _check(f"verdict approved (got {run1.verdict})", run1.verdict == ReviewVerdict.APPROVED)
    approve_writes = [w for w in recorder.github_writes if w["kind"] == "approve_review"]
    _check("APPROVE review posted to GitHub", len(approve_writes) == 1)
    _log(f"recorded approve review: {json.dumps(approve_writes[0]['body'])}")

    # ---------------------------------------------------------------
    _step("STEP 3: PR #101 synchronize -> supersede the in-flight run")
    # 3a: leave a run QUEUED (Temporal not yet picked it up) so the next push can supersede it.
    workflow_state["enabled"] = False
    recorder.register_pr(REPO, 101, _pr_object(101, author, "sha101b", "Add util helper"), _pr_files())
    sync1 = payloads.build_pull_request_event(
        action="synchronize",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=101,
        title="Add util helper",
        body="Adds a small helper and a test.",
        author_login=author,
        head_sha="sha101b",
        head_ref="feat/pr-101",
        base_sha=BASE_SHA,
    )
    _post_webhook(client, sync1)
    run2 = ReviewRun.objects.for_team(team_id).filter(pull_request=pr, head_sha="sha101b").latest("created_at")
    _check(f"run2 left QUEUED (got {run2.status})", run2.status == ReviewRunStatus.QUEUED)

    # 3b: next push supersedes the queued run2 and gets reviewed for real.
    workflow_state["enabled"] = True
    recorder.register_pr(REPO, 101, _pr_object(101, author, "sha101c", "Add util helper"), _pr_files())
    sync2 = payloads.build_pull_request_event(
        action="synchronize",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=101,
        title="Add util helper",
        body="Adds a small helper and a test.",
        author_login=author,
        head_sha="sha101c",
        head_ref="feat/pr-101",
        base_sha=BASE_SHA,
    )
    _post_webhook(client, sync2)
    run2.refresh_from_db()
    run3 = ReviewRun.objects.for_team(team_id).filter(pull_request=pr, head_sha="sha101c").latest("created_at")
    _check(f"run2 SUPERSEDED (got {run2.status})", run2.status == ReviewRunStatus.SUPERSEDED)
    _check(
        f"run3 COMPLETED approved (got {run3.status}/{run3.verdict})",
        run3.status == ReviewRunStatus.COMPLETED and run3.verdict == ReviewVerdict.APPROVED,
    )

    # ---------------------------------------------------------------
    _step("STEP 4: PR #101 closed+merged -> merge facts + audience_key stamped")
    merged = payloads.build_pull_request_event(
        action="closed",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=101,
        title="Add util helper",
        body="Adds a small helper and a test.",
        author_login=author,
        head_sha="sha101c",
        head_ref="feat/pr-101",
        base_sha=BASE_SHA,
        merged=True,
        merged_at="2026-07-13T10:00:00Z",
        merge_commit_sha="merge101",
        additions=28,
        deletions=1,
        changed_files=2,
    )
    _post_webhook(client, merged)
    pr.refresh_from_db()
    _check("merged_at recorded", pr.merged_at is not None)
    _check(f"merge_commit_sha recorded (got {pr.merge_commit_sha})", pr.merge_commit_sha == "merge101")
    _check(f"audience_key == 'team-devex' (got '{pr.audience_key}')", pr.audience_key == "team-devex")

    # ---------------------------------------------------------------
    _step("STEP 5: daily digest -> auto-provision 'team-devex' channel + Slack post")
    FakeSlackIntegration.reset(channels=[{"id": "C-DEVEX", "name": "team-devex"}])
    send_daily_digests()

    channel = DigestChannel.objects.for_team(team_id).filter(audience_key="team-devex").first()
    _check("DigestChannel 'team-devex' auto-provisioned", channel is not None)
    assert channel is not None
    _check(
        f"resolution_source slack_name_match (got {channel.resolution_source})",
        channel.resolution_source == "slack_name_match",
    )
    _check("channel enabled", channel.enabled is True)
    digest_run = DigestRun.objects.for_team(team_id).filter(digest_channel=channel).latest("created_at")
    _check(f"DigestRun completed (got {digest_run.status})", digest_run.status == "completed")
    _check("Slack chat_postMessage recorded", len(FakeSlackIntegration.posted_messages) == 1)
    posted = FakeSlackIntegration.posted_messages[0]
    _log(f"posted to channel={posted['channel']} ts={digest_run.slack_message_ts}")
    _log("blocks:\n" + json.dumps(posted["blocks"], indent=2))

    # ---------------------------------------------------------------
    _step("STEP 6: merged PR by author with no team + no declared channel -> stays undigested")
    loner = "loner-dev"  # deliberately absent from teams_by_login
    recorder.register_pr(REPO, 202, _pr_object(202, loner, "sha202a", "Bump dep"), _pr_files())
    open_202 = payloads.build_pull_request_event(
        action="opened",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=202,
        title="Bump dep",
        body="Routine bump.",
        author_login=loner,
        head_sha="sha202a",
        head_ref="feat/pr-202",
        base_sha=BASE_SHA,
    )
    _post_webhook(client, open_202)  # review + approve so the merge is digest-eligible
    merged_202 = payloads.build_pull_request_event(
        action="closed",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=202,
        title="Bump dep",
        body="Routine bump.",
        author_login=loner,
        head_sha="sha202a",
        head_ref="feat/pr-202",
        base_sha=BASE_SHA,
        merged=True,
        merged_at="2026-07-13T11:00:00Z",
        merge_commit_sha="merge202",
        additions=2,
        deletions=2,
        changed_files=1,
    )
    _post_webhook(client, merged_202)
    pr202 = PullRequest.objects.for_team(team_id).get(repo_config=repo_config, pr_number=202)
    _check(f"audience_key is repo-fallback (got '{pr202.audience_key}')", pr202.audience_key == f"repo:{REPO}")

    FakeSlackIntegration.reset(channels=[{"id": "C-DEVEX", "name": "team-devex"}])  # no channel named repo:...
    send_daily_digests()
    pr202.refresh_from_db()
    repo_channel = DigestChannel.objects.for_team(team_id).filter(audience_key=f"repo:{REPO}").first()
    _check("no channel provisioned for repo: audience", repo_channel is None)
    _check("PR #202 remains undigested (digest_run is NULL)", pr202.digest_run_id is None)

    _step("DONE — full chain exercised")
    _log(f"github writes recorded: {len(recorder.github_writes)}")
    _log(f"slack messages posted:  {FakeSlackIntegration.total_posted}")


def _generate_app_private_key() -> str:
    """Ephemeral RSA key so the real App-JWT mint path runs (the token POST itself is faked)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def run_scenario() -> None:
    """Run the whole chain end to end, printing a readable trace and asserting at each step."""
    keep = os.environ.get("KEEP") == "1"
    sandbox_mode = os.environ.get("SANDBOX_MODE", "stub")
    recorder = fake_github.GitHubRecorder()
    _configure_github(recorder)
    exec_log: list[str] = []
    workflow_state = {"enabled": True}

    _step("SETUP: team, integration, repo config, GitHub/Slack fakes")
    team_id, integration_id, cleanup_org = _setup_team()

    with ExitStack() as stack:
        # Product reads -> writer connection, so an in-flight write is visible to the next read
        # (mirrors the pytest product-DB environment; see the module docstring).
        stack.enter_context(patch("posthog.product_db_router.TEST", True))
        # Task transaction -> stamphog writer + inline on_commit (see _TxShim).
        stack.enter_context(patch("products.stamphog.backend.tasks.tasks.transaction", _TxShim()))
        stack.enter_context(
            override_settings(
                CELERY_TASK_ALWAYS_EAGER=True,
                CELERY_TASK_EAGER_PROPAGATES=True,
                STAMPHOG_GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET,
                STAMPHOG_GITHUB_APP_ID="123456",
                STAMPHOG_GITHUB_APP_PRIVATE_KEY=_generate_app_private_key(),
            )
        )
        stack.enter_context(
            patch("products.stamphog.backend.logic.github_client.github_request", recorder.github_request)
        )
        stack.enter_context(
            patch(
                "products.stamphog.backend.logic.github_client.remember_observed_core_limit",
                fake_github.noop_remember_observed_core_limit,
            )
        )
        stack.enter_context(
            patch(
                "products.stamphog.backend.logic.github_client.raise_if_github_rate_limited",
                fake_github.noop_raise_if_github_rate_limited,
            )
        )
        stack.enter_context(
            patch(
                "products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow",
                _make_fake_workflow(workflow_state),
            )
        )
        stack.enter_context(
            patch("products.stamphog.backend.logic.slack_digest.SlackIntegration", FakeSlackIntegration)
        )
        stack.enter_context(
            patch("products.stamphog.backend.logic.channel_resolution.SlackIntegration", FakeSlackIntegration)
        )
        # Digest LLM: force the deterministic fallback (no gateway needed) by making acquisition raise.
        stack.enter_context(
            patch(
                "products.stamphog.backend.logic.digest.get_llm_client",
                side_effect=RuntimeError("no gateway in harness"),
            )
        )
        if sandbox_mode == "stub":
            fake_cls = _make_fake_sandbox_class(_approved_engine_output(), exec_log)
            stack.enter_context(
                patch(
                    "products.stamphog.backend.temporal.activities.get_sandbox_class_for_backend",
                    lambda backend: fake_cls,
                )
            )
            _log("sandbox mode: stub (scripted APPROVED engine output)")
        else:
            _log("sandbox mode: real (docker) — needs a real repo + installation; not exercised by the fakes")

        client = Client()
        try:
            _run_steps(client, team_id, recorder, workflow_state)
        finally:
            if keep:
                _log("KEEP=1 — leaving harness rows in place. Call cleanup(team_id, integration_id, org).")
            else:
                cleanup(team_id, integration_id, cleanup_org)


def cleanup(team_id: int, integration_id: int | None, cleanup_org: Any) -> None:
    """Delete every row the harness committed. Stamphog rows are on a separate DB (no FK cascade).

    Best-effort: Team deletion fires cache-clear signals that hit Redis, so with the dev stack
    down (Redis unavailable) the org delete is skipped with a warning rather than crashing.
    """
    _step("CLEANUP")
    for model in (DigestRun, ReviewRun, PullRequest, DigestChannel, StamphogRepoConfig):
        deleted = model.objects.unscoped().filter(team_id=team_id).delete()
        _log(f"deleted {model.__name__}: {deleted}")
    if integration_id is not None:
        _best_effort(
            lambda: Integration.objects.filter(id=integration_id).delete(), f"delete Integration id={integration_id}"
        )
    if cleanup_org is not None:
        _best_effort(cleanup_org.delete, "delete org 'stamphog-harness' (cascades team + project)")
    else:
        _log("reused team — left the team itself untouched")


def _best_effort(action: Any, label: str) -> None:
    try:
        action()
        _log(f"deleted: {label}")
    except Exception as e:  # noqa: BLE001 — cleanup must not mask the scenario result
        _log(f"skipped ({label}) — {type(e).__name__}: {e}. Re-run cleanup with the dev stack up.")


# Piped through `manage.py shell`, so just run it — but stay import-safe (the module name
# only matches when imported as a package, not when exec'd from stdin).
if __name__ != "products.stamphog.backend.dev.harness":
    run_scenario()
