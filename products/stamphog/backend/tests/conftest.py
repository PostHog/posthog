import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import patch

from django.test import Client, override_settings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.models import OAuthApplication
from posthog.models.scoping import team_scope
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV, ARRAY_APP_CLIENT_ID_EU, ARRAY_APP_CLIENT_ID_US

from products.stamphog.backend.temporal.activities import (
    MarkReviewFailedInput,
    StamphogReviewInput,
    dismiss_stale_approvals,
    fetch_review_context,
    list_in_flight_reviewer_bots,
    mark_review_failed,
    post_verdict,
    run_review_in_sandbox,
    signal_review_started,
)
from products.stamphog.backend.tests import fakes

PRODUCT_DATABASES = {"default", "stamphog_db_writer", "stamphog_db_reader"}


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    """Set team context for raw pytest tests that hit the database.

    ProductTeamModel is fail-closed — queries without context raise
    TeamScopeError. TestCase / APIBaseTest subclasses create their own team in
    setUp() and are skipped here (getfixturevalue("team") would duplicate-create
    with the same api_token); those use StamphogTeamScopedTestMixin instead.
    """
    if request.node.get_closest_marker("django_db") is None:
        yield
        return

    is_django_testcase = request.cls is not None and any(cls.__name__ == "TestCase" for cls in request.cls.__mro__)
    if is_django_testcase:
        yield
        return

    team = request.getfixturevalue("team")
    with team_scope(team.id):
        yield


class StamphogTeamScopedTestMixin:
    """Mixin for TestCase / APIBaseTest tests that use ProductTeamModel.

    Wraps setUp/tearDown with team_scope so the test body's queries find a
    scope. Place BEFORE APIBaseTest in the MRO so its setUp runs first
    (creating self.team) and ours can use it.
    """

    _team_scope_cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._team_scope_cm = cm

    def tearDown(self) -> None:
        if self._team_scope_cm is not None:
            try:
                self._team_scope_cm.__exit__(None, None, None)
            finally:
                self._team_scope_cm = None
        super().tearDown()  # type: ignore[misc]


WEBHOOK_PATH = "/webhooks/stamphog/github"
WEBHOOK_SECRET = "integration-webhook-secret"


def _generate_app_private_key() -> str:
    """Ephemeral RSA key so the real App-JWT mint path runs (the token POST itself is faked)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _run_activity(activity_fn: Any, arg: Any) -> Any:
    """Run a stamphog activity's plain sync body in-thread.

    The activities are ``@activity.defn`` over ``@asyncify``; ``__wrapped__`` is the original
    sync function, callable directly so it shares the test's DB connection (production drives the
    same body from a Temporal worker thread instead).
    """
    return activity_fn.__wrapped__(arg)


def _inline_review_workflow(review_run_id: str, team_id: int) -> None:
    """Stand in for the Temporal client by driving the real activities in order.

    Mirrors StamphogReviewWorkflow: dismiss stale approvals FIRST (fail-closed — even a context-fetch
    failure must not leave an earlier head's approval standing), signal the review has started (the
    "review in flight" 👀), then fetch context, run in the (faked) sandbox, post the verdict; on any
    error mark the run failed, exactly like the workflow's failure path.
    """
    inp = StamphogReviewInput(review_run_id=review_run_id, team_id=team_id)
    try:
        _run_activity(dismiss_stale_approvals, inp)
        _run_activity(signal_review_started, inp)
        _run_activity(fetch_review_context, inp)
        # One bot-wait poll, no sleeping: mirrors the workflow's loop semantics (refresh the
        # reactions snapshot, then proceed) without its durable timers.
        _run_activity(list_in_flight_reviewer_bots, inp)
        _run_activity(run_review_in_sandbox, inp)
        _run_activity(post_verdict, inp)
    except Exception as e:  # noqa: BLE001 — mirror the workflow's failure path
        _run_activity(mark_review_failed, MarkReviewFailedInput(review_run_id, team_id, str(e)))


@dataclass
class StamphogChain:
    """Handle for a wired-up full chain: the GitHub recorder plus a webhook poster."""

    recorder: fakes.GitHubRecorder
    client: Client
    # Every file the fake sandbox had written into the checkout, as (path, payload) — lets a test
    # assert what was injected (e.g. default policy files when the repo carries none).
    sandbox_writes: list[tuple[str, bytes]]
    # The fake sandbox class itself, so a test can script failure modes (destroy_error) and read
    # captured create() configs (created_configs). Typed Any: the class attrs are fake-only.
    sandbox_class: Any

    def post_webhook(self, payload: dict[str, Any], *, delivery_id: str) -> int:
        body = fakes.encode(payload)
        return self.client.post(
            WEBHOOK_PATH,
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=fakes.sign_payload(body, WEBHOOK_SECRET),
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_GITHUB_DELIVERY=delivery_id,
        ).status_code


@pytest.fixture
def stamphog_chain() -> Iterator[StamphogChain]:
    """Wire the four chain boundaries (GitHub, Slack, sandbox, LLM) to deterministic fakes.

    The Temporal client is replaced with an inline runner of the real activities, and the task's
    ``on_commit`` fires inline (the test's outer transaction never really commits). Everything else
    runs as production code.
    """
    recorder = fakes.GitHubRecorder()
    # review-guidance.md is a required trusted policy file — run_review_in_sandbox fails closed without
    # it — so seed it for the whole chain; individual tests still set/override policy.yml as they need.
    recorder.policy_files[".stamphog/review-guidance.md"] = "Review PostHog PRs against the repo's norms.\n"
    # The review activity mints a real sandbox OAuth token under the Array app, which resolves by
    # region client id — seed every region so get_instance_region()'s value doesn't matter here.
    for client_id in (ARRAY_APP_CLIENT_ID_DEV, ARRAY_APP_CLIENT_ID_US, ARRAY_APP_CLIENT_ID_EU):
        OAuthApplication.objects.get_or_create(
            client_id=client_id,
            defaults={
                "name": "Array Test App",
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://app.posthog.com/callback",
                # RS256 is enforced by the `enforce_rs256_algorithm` DB constraint.
                "algorithm": "RS256",
            },
        )
    fake_slack = fakes.FakeSlackIntegration
    fake_slack.reset(channels=[])
    sandbox_writes: list[tuple[str, bytes]] = []
    fake_sandbox = fakes.make_fake_sandbox_class(fakes.approved_engine_output(), write_sink=sandbox_writes)

    with ExitStack() as stack:
        stack.enter_context(
            override_settings(
                STAMPHOG_GITHUB_APP_WEBHOOK_SECRET=WEBHOOK_SECRET,
                STAMPHOG_GITHUB_APP_ID="123456",
                STAMPHOG_GITHUB_APP_PRIVATE_KEY=_generate_app_private_key(),
            )
        )
        # Hosted reviews hard-require the gateway (no raw-Anthropic fallback); point it at the
        # stamphog product route like production would.
        stack.enter_context(patch.dict(os.environ, {"AI_GATEWAY_URL": "https://llm-gateway.test/stamphog/v1"}))
        # mark_review_failed emits a failure event through the real analytics client — a network
        # boundary, faked like the rest. Tests asserting on the event re-patch this locally.
        stack.enter_context(patch("products.stamphog.backend.temporal.activities.ph_scoped_capture"))
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
            patch(
                "products.stamphog.backend.temporal.activities.get_sandbox_class_for_backend",
                lambda backend: fake_sandbox,
            )
        )
        stack.enter_context(
            patch("products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow", _inline_review_workflow)
        )
        stack.enter_context(
            patch(
                "products.stamphog.backend.tasks.tasks.transaction.on_commit", side_effect=lambda fn, using=None: fn()
            )
        )
        stack.enter_context(patch("products.stamphog.backend.logic.slack_digest.SlackIntegration", fake_slack))
        stack.enter_context(patch("products.stamphog.backend.logic.channel_resolution.SlackIntegration", fake_slack))
        stack.enter_context(
            patch(
                "products.stamphog.backend.logic.digest.get_llm_client",
                side_effect=RuntimeError("no gateway in tests"),
            )
        )
        yield StamphogChain(
            recorder=recorder, client=Client(), sandbox_writes=sandbox_writes, sandbox_class=fake_sandbox
        )
