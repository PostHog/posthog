"""Interactive, laptop-runnable smoke of the stamphog full chain — real sandbox capable.

The deterministic coverage lives in the pytest suite (products/stamphog/backend/tests/
test_integration.py), which fakes all four boundaries. This runner exists for the one thing
those tests deliberately don't do: drive the review through a REAL docker/Modal sandbox against
a real ANTHROPIC/AI-gateway key, and print the resulting Slack digest blocks so a human can
eyeball them. It reuses the exact same fakes as the tests (products.stamphog.backend.tests.fakes)
so there is no parallel fake setup — GitHub and Slack are always faked; only the sandbox is real
when asked.

Invocation (from repo root, dev stack up — Postgres + Redis):

    flox activate -- bash -c 'DEBUG=1 ./manage.py shell < products/stamphog/backend/dev/run_scenario.py'

Real-sandbox smoke (needs a real LLM key and a sandbox backend):

    SANDBOX_MODE=real SANDBOX_PROVIDER=docker ANTHROPIC_API_KEY=sk-ant-... \
      flox activate -- bash -c 'DEBUG=1 ./manage.py shell < products/stamphog/backend/dev/run_scenario.py'

    # Modal instead of docker: SANDBOX_PROVIDER=MODAL_DOCKER plus a logged-in `modal token`.

Env knobs:
    SANDBOX_MODE=stub|real   stub (default) injects a scripted APPROVED verdict; real runs the
                             production sandbox (needs a real repo + installation reachable by
                             the App credentials, so the GitHub fake's scripted PR won't clone —
                             point REPO/INSTALLATION_ID at something real for a true end-to-end run)
    KEEP=1                   leave the scenario rows in place instead of deleting them at the end

If the stamphog product DB is missing, create it once:
    flox activate -- bash -c 'DEBUG=1 ./manage.py migrate_product_databases'
"""

from __future__ import annotations

import os
import json
import uuid
from contextlib import ExitStack
from typing import Any

from unittest.mock import patch

from django.db import transaction
from django.test import Client, override_settings

from posthog.models.integration import Integration
from posthog.models.organization import Organization

from products.stamphog.backend.facade.enums import ReviewRunStatus
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
from products.stamphog.backend.tests import fakes

WEBHOOK_PATH = "/webhooks/stamphog/github"
WEBHOOK_SECRET = "scenario-webhook-secret"
REPO = "harness/widgets"
INSTALLATION_ID = "scenario-inst-1"
BASE_SHA = "base000"
WRITER_DB = "stamphog_db_writer"


def _log(msg: str) -> None:
    print(f"  · {msg}")  # noqa: T201 — dev runner prints a trace


def _step(title: str) -> None:
    print("\n" + "=" * 72 + f"\n# {title}\n" + "=" * 72)  # noqa: T201 — dev runner prints a trace


class _TxShim:
    """Drop-in for the ``transaction`` reference in ``tasks/tasks.py``, needed ONLY outside pytest.

    The pytest suite gets the product-DB transaction plumbing for free from its fixtures; this runner
    executes under ``manage.py shell`` where it doesn't. ``atomic()`` targets the stamphog writer so
    the task's ``select_for_update`` runs in a real product-DB transaction that commits within the
    task; ``on_commit`` runs inline so the inline workflow fires while the rows are visible.
    """

    def atomic(self, *args: Any, **kwargs: Any) -> Any:
        return transaction.atomic(using=WRITER_DB)

    def on_commit(self, func: Any, using: Any = None) -> None:
        func()


def _inline_review_workflow(review_run_id: str, team_id: int) -> None:
    """Mirror StamphogReviewWorkflow by driving the real activities in order (sync bodies)."""
    inp = StamphogReviewInput(review_run_id=review_run_id, team_id=team_id)
    try:
        fetch_review_context.__wrapped__(inp)
        run_review_in_sandbox.__wrapped__(inp)
        post_verdict.__wrapped__(inp)
    except Exception as e:  # noqa: BLE001 — mirror the workflow's failure path
        _log(f"workflow error, marking run failed: {e}")
        mark_review_failed.__wrapped__(MarkReviewFailedInput(review_run_id, team_id, str(e)))


def _post_webhook(client: Client, payload: dict[str, Any]) -> int:
    body = fakes.encode(payload)
    return client.post(
        WEBHOOK_PATH,
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=fakes.sign_payload(body, WEBHOOK_SECRET),
        HTTP_X_GITHUB_EVENT="pull_request",
        HTTP_X_GITHUB_DELIVERY=str(uuid.uuid4()),
    ).status_code


def _pr_object(number: int, author: str, head_sha: str) -> dict:
    return {
        "number": number,
        "title": f"PR {number}",
        "body": "Adds a small helper and a test.",
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "user": {"login": author},
        "head": {"sha": head_sha, "ref": f"feat/pr-{number}"},
        "base": {"sha": BASE_SHA, "ref": "master"},
        "draft": False,
    }


def _run_scenario(client: Client, team_id: int, recorder: fakes.GitHubRecorder) -> None:
    StamphogRepoConfig.objects.for_team(team_id).create(
        team_id=team_id, repository=REPO, installation_id=INSTALLATION_ID, enabled=True, digest_enabled=True
    )
    author = "devex-dev"
    recorder.teams_by_login[author] = ["team-devex"]
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"

    _step("PR #101 opened -> review -> APPROVE posted")
    recorder.register_pr(
        REPO,
        101,
        _pr_object(101, author, "sha101a"),
        [{"filename": "src/util.py", "status": "modified", "additions": 8, "deletions": 1, "patch": "@@ -1 +1 @@"}],
    )
    status = _post_webhook(
        client,
        fakes.build_pull_request_event(
            action="opened",
            installation_id=INSTALLATION_ID,
            repo=REPO,
            number=101,
            title="PR 101",
            body="Adds a small helper and a test.",
            author_login=author,
            head_sha="sha101a",
            head_ref="feat/pr-101",
            base_sha=BASE_SHA,
        ),
    )
    run = ReviewRun.objects.for_team(team_id).filter(pull_request__pr_number=101).latest("created_at")
    _log(f"webhook {status}; ReviewRun {run.status}/{run.verdict}")
    approvals = [w for w in recorder.github_writes if w["kind"] == "approve_review"]
    _log(f"approve reviews recorded: {len(approvals)}")
    assert run.status == ReviewRunStatus.COMPLETED

    _step("PR #101 merged -> audience_key stamped")
    _post_webhook(
        client,
        fakes.build_pull_request_event(
            action="closed",
            installation_id=INSTALLATION_ID,
            repo=REPO,
            number=101,
            title="PR 101",
            body="Adds a small helper and a test.",
            author_login=author,
            head_sha="sha101a",
            head_ref="feat/pr-101",
            base_sha=BASE_SHA,
            merged=True,
            merged_at="2026-07-13T10:00:00Z",
            merge_commit_sha="merge101",
        ),
    )
    pr = PullRequest.objects.for_team(team_id).get(pr_number=101)
    _log(f"audience_key={pr.audience_key!r} merge_commit_sha={pr.merge_commit_sha!r}")

    _step("daily digest -> auto-provision channel + Slack post")
    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-DEVEX", "name": "team-devex"}])
    send_daily_digests()
    posted = fakes.FakeSlackIntegration.posted_messages
    _log(f"slack messages posted: {len(posted)}")
    for message in posted:
        _log(f"channel={message['channel']}\n" + json.dumps(message["blocks"], indent=2))


def run_scenario() -> None:
    sandbox_mode = os.environ.get("SANDBOX_MODE", "stub")
    keep = os.environ.get("KEEP") == "1"
    recorder = fakes.GitHubRecorder()

    _step("SETUP: team, slack integration, GitHub/Slack fakes")
    org, _, team = Organization.objects.bootstrap(user=None, name="stamphog-scenario")
    team_id = team.id
    integration = Integration.objects.create(
        team_id=team_id,
        kind="slack",
        config={"authed_user": {"id": "U-scenario"}},
        sensitive_config={"access_token": "xoxb-scenario-fake"},
    )
    _log(f"team id={team_id}, slack integration id={integration.id}")

    with ExitStack() as stack:
        stack.enter_context(patch("posthog.product_db_router.TEST", True))
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
                fakes.noop_remember_observed_core_limit,
            )
        )
        stack.enter_context(
            patch(
                "products.stamphog.backend.logic.github_client.raise_if_github_rate_limited",
                fakes.noop_raise_if_github_rate_limited,
            )
        )
        stack.enter_context(
            patch("products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow", _inline_review_workflow)
        )
        stack.enter_context(
            patch("products.stamphog.backend.logic.slack_digest.SlackIntegration", fakes.FakeSlackIntegration)
        )
        stack.enter_context(
            patch("products.stamphog.backend.logic.channel_resolution.SlackIntegration", fakes.FakeSlackIntegration)
        )
        stack.enter_context(
            patch(
                "products.stamphog.backend.logic.digest.get_llm_client",
                side_effect=RuntimeError("no gateway in scenario"),
            )
        )
        if sandbox_mode == "stub":
            fake_sandbox = fakes.make_fake_sandbox_class(fakes.approved_engine_output())
            stack.enter_context(
                patch(
                    "products.stamphog.backend.temporal.activities.get_sandbox_class_for_backend",
                    lambda backend: fake_sandbox,
                )
            )
            _log("sandbox mode: stub (scripted APPROVED engine output)")
        else:
            _log("sandbox mode: real — running the production sandbox (needs a real repo + LLM key)")

        try:
            _run_scenario(Client(), team_id, recorder)
        finally:
            if keep:
                _log("KEEP=1 — leaving scenario rows in place")
            else:
                _cleanup(team_id, integration.id, org)


def _generate_app_private_key() -> str:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415 — heavy crypto import, dev-only path
    from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: PLC0415 — heavy crypto import, dev-only path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def _cleanup(team_id: int, integration_id: int, org: Any) -> None:
    _step("CLEANUP")
    for model in (DigestRun, ReviewRun, PullRequest, DigestChannel, StamphogRepoConfig):
        model.objects.unscoped().filter(team_id=team_id).delete()
    try:
        Integration.objects.filter(id=integration_id).delete()
        org.delete()
        _log("deleted scenario org + rows")
    except Exception as e:  # noqa: BLE001 — cleanup must not mask the scenario result
        _log(f"partial cleanup ({type(e).__name__}: {e}); re-run with the dev stack up for a full teardown")


# Piped through `manage.py shell`, so just run it — but stay import-safe.
if __name__ != "products.stamphog.backend.dev.run_scenario":
    run_scenario()
