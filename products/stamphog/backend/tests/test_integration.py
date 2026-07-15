import json
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.integration import Integration

from products.stamphog.backend.facade.enums import (
    ChannelResolutionSource,
    DigestRunStatus,
    ReviewMode,
    ReviewRunStatus,
    ReviewVerdict,
)
from products.stamphog.backend.models import DigestChannel, DigestRun, PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tasks.digest import send_daily_digests
from products.stamphog.backend.temporal.activities import (
    MarkReviewFailedInput,
    StamphogReviewInput,
    dismiss_stale_approvals,
    mark_review_failed,
    post_verdict,
)
from products.stamphog.backend.temporal.constants import STAMPHOG_SANDBOX_REPO_DIR
from products.stamphog.backend.tests import fakes
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, StamphogChain

REPO = "acme/widgets"
INSTALLATION_ID = "2001"
BASE_SHA = "base000"
POLICY_DEFAULTS_DIR = Path(__file__).resolve().parents[1] / "policy_defaults"


def _repo_config(team_id: int, *, digest_enabled: bool = True) -> StamphogRepoConfig:
    return StamphogRepoConfig.objects.for_team(team_id).create(
        team_id=team_id,
        repository=REPO,
        installation_id=INSTALLATION_ID,
        enabled=True,
        digest_enabled=digest_enabled,
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
        merged_at="2026-07-13T10:00:00Z",
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
    "prior_head,prior_dismissed,expect_dismissed",
    [
        ("sha-old", False, True),
        ("sha-new", False, False),
        ("sha-old", True, False),
    ],
    ids=["old_head_dismissed_and_stamped", "same_head_untouched", "already_dismissed_not_redone"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_dismiss_stale_approvals(
    team, stamphog_chain: StamphogChain, prior_head: str, prior_dismissed: bool, expect_dismissed: bool
) -> None:
    # A prior stamphog approval posted at an earlier head must be dismissed on GitHub and stamped when a
    # new run at a different head runs. An approval at the same head, or one already dismissed, is left
    # alone (GitHub never auto-dismisses, so an undismissed old-head approval would still count).
    repo_config = _repo_config(team.id)
    pull_request = PullRequest.objects.for_team(team.id).create(
        team_id=team.id, repo_config=repo_config, pr_number=101, author_login="devex-dev"
    )
    prior = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id,
        pull_request=pull_request,
        head_sha=prior_head,
        status=ReviewRunStatus.COMPLETED,
        verdict=ReviewVerdict.APPROVED,
        posted_review_id=555,
        approval_dismissed_at=timezone.now() if prior_dismissed else None,
    )
    current = ReviewRun.objects.for_team(team.id).create(
        team_id=team.id, pull_request=pull_request, head_sha="sha-new", status=ReviewRunStatus.QUEUED
    )

    dismiss_stale_approvals.__wrapped__(StamphogReviewInput(review_run_id=str(current.id), team_id=team.id))

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


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_mark_review_failed_captures_failure_event(team) -> None:
    # Hosted failures used to be visible only in worker logs; the dashboards need the
    # stamphog_review_failed event next to the review-completed ones.
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
        mark_review_failed.__wrapped__(MarkReviewFailedInput(str(run.id), team.id, "sandbox exploded"))

    run.refresh_from_db()
    assert run.status == ReviewRunStatus.FAILED
    assert capture_fn.call_args.kwargs["event"] == "stamphog_review_failed"
    assert capture_fn.call_args.kwargs["distinct_id"] == "devex-dev"
    props = capture_fn.call_args.kwargs["properties"]
    assert props["stamphog_repo"] == REPO
    assert props["stamphog_error"] == "sandbox exploded"


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

    post_verdict.__wrapped__(StamphogReviewInput(review_run_id=str(run.id), team_id=team.id))

    run.refresh_from_db()
    assert run.verdict == ReviewVerdict.REFUSED
    label_removals = [w for w in stamphog_chain.recorder.github_writes if w["kind"] == "remove_label"]
    if expect_strip:
        assert label_removals == [{"kind": "remove_label", "repo": REPO, "number": 101, "label": "stamphog"}]
    else:
        assert label_removals == []


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
    team, stamphog_chain: StamphogChain, approved_at_sha: str | None, expected_audience_key: str
) -> None:
    # Regression guard: the approved-head_sha eligibility gate plus the author -> GitHub-team
    # audience cascade. Merge facts are always recorded, but audience_key is stamped (via the
    # cascade) only when a stamphog-approved run exists at the exact merged head SHA.
    repo_config = _repo_config(team.id)
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
def test_daily_digest_auto_provisions_channel_and_posts(team, stamphog_chain: StamphogChain) -> None:
    # Regression guard: the digest fan-out + auto-provision (Slack name match) + Slack post. An
    # approved-merged PR with no channel yet must provision an enabled DigestChannel by matching
    # its audience_key to a workspace channel name, complete a DigestRun, and post the digest.
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
    assert channel.enabled is True
    assert channel.resolution_source == ChannelResolutionSource.SLACK_NAME_MATCH
    assert channel.slack_integration_id == integration.id

    run = DigestRun.objects.for_team(team.id).get(digest_channel=channel)
    assert run.status == DigestRunStatus.COMPLETED

    posted = fakes.FakeSlackIntegration.posted_messages
    assert len(posted) == 1
    assert posted[0]["channel"] == "C-DEVEX"
    assert posted[0]["blocks"][0]["text"]["text"] == "Merged PRs digest"
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
