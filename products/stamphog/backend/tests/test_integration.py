import uuid

import pytest

from django.utils import timezone

from posthog.models.integration import Integration

from products.stamphog.backend.facade.enums import (
    ChannelResolutionSource,
    DigestRunStatus,
    ReviewRunStatus,
    ReviewVerdict,
)
from products.stamphog.backend.models import DigestChannel, DigestRun, PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tasks.digest import send_daily_digests
from products.stamphog.backend.tests import fakes
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, StamphogChain

REPO = "acme/widgets"
INSTALLATION_ID = "2001"
BASE_SHA = "base000"


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
