import json
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.stamphog.backend.facade.enums import DigestRunStatus
from products.stamphog.backend.logic.digest import DigestSummary, summarize_merged_prs
from products.stamphog.backend.models import DigestChannel, DigestRun, PullRequest, StamphogRepoConfig
from products.stamphog.backend.tasks.digest import send_digest_for_channel
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES

REPO = "acme/widgets"
AUDIENCE = "team-devex"


def _summary(prs: list[PullRequest]) -> DigestSummary:
    """Stand in for the LLM so the task never reaches a gateway."""
    return DigestSummary(intro=f"{len(prs)} merged.", prs=[])


def _seed_channel_and_prs(team_id: int, pr_count: int = 2) -> str:
    repo_config = StamphogRepoConfig.objects.for_team(team_id).create(
        team_id=team_id, repository=REPO, installation_id="9001"
    )
    channel = DigestChannel.objects.for_team(team_id).create(
        team_id=team_id, audience_key=AUDIENCE, slack_integration_id=1, slack_channel_id="C1"
    )
    for number in range(1, pr_count + 1):
        PullRequest.objects.for_team(team_id).create(
            team_id=team_id, repo_config=repo_config, pr_number=number, audience_key=AUDIENCE
        )
    return str(channel.id)


# ---- Finding 2: a channel's digest must never post to Slack twice ------------------------------


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_concurrent_runs_for_one_channel_post_to_slack_once(team) -> None:
    # Two workers firing for the same channel would both read the same unlinked PRs and both post.
    # The fix claims the PRs (links them to a run) before posting, so a second worker that starts
    # mid-post finds nothing unlinked and returns without posting. Re-entering post_digest simulates
    # that overlap deterministically.
    channel_id = _seed_channel_and_prs(team.id)
    posts: list[str] = []

    def reentrant_post(team_id: int, channel: Any, summary: Any) -> str:
        posts.append(str(channel.id))
        if len(posts) == 1:  # a second worker starts while the first is posting
            send_digest_for_channel(digest_channel_id=str(channel.id), team_id=team_id)
        return f"ts-{len(posts)}"

    with (
        patch("products.stamphog.backend.tasks.digest.post_digest", side_effect=reentrant_post),
        patch("products.stamphog.backend.tasks.digest.summarize_merged_prs", side_effect=_summary),
    ):
        send_digest_for_channel(digest_channel_id=channel_id, team_id=team.id)

    assert len(posts) == 1  # the re-entrant worker found no unlinked PRs and did not post
    with team_scope(team.id):
        completed = list(DigestRun.objects.filter(status=DigestRunStatus.COMPLETED))
        assert len(completed) == 1
        assert PullRequest.objects.filter(digest_run__isnull=True).count() == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_failed_slack_post_leaves_prs_retryable_next_run(team) -> None:
    # A Slack failure must not hide the PRs: they're claimed before posting, so on failure they have
    # to be unlinked again (the retry query filters digest_run__isnull=True). Otherwise they'd stay
    # bound to a FAILED run and never retry.
    channel_id = _seed_channel_and_prs(team.id)

    with (
        patch("products.stamphog.backend.tasks.digest.post_digest", side_effect=RuntimeError("slack down")),
        patch("products.stamphog.backend.tasks.digest.summarize_merged_prs", side_effect=_summary),
    ):
        send_digest_for_channel(digest_channel_id=channel_id, team_id=team.id)

    with team_scope(team.id):
        run = DigestRun.objects.get()
        assert run.status == DigestRunStatus.FAILED
        assert PullRequest.objects.filter(digest_run__isnull=True).count() == 2  # unlinked, retryable

    with (
        patch("products.stamphog.backend.tasks.digest.post_digest", return_value="ts-ok"),
        patch("products.stamphog.backend.tasks.digest.summarize_merged_prs", side_effect=_summary),
    ):
        send_digest_for_channel(digest_channel_id=channel_id, team_id=team.id)

    with team_scope(team.id):
        completed = DigestRun.objects.get(status=DigestRunStatus.COMPLETED)
        assert PullRequest.objects.filter(digest_run=completed).count() == 2  # retry picked them up


# ---- Finding 3: same PR number from different repos must not collapse --------------------------


def _pr_stub(repository: str, pr_number: int, title: str, url: str) -> PullRequest:
    """Unsaved PullRequest with just the fields the summarizer reads — no DB needed."""
    repo_config = StamphogRepoConfig(repository=repository, installation_id="x")
    return PullRequest(
        repo_config=repo_config,
        team_id=7,
        pr_number=pr_number,
        title=title,
        pr_url=url,
        author_login="dev",
        additions=1,
        deletions=0,
        changed_files=1,
        body_excerpt="",
    )


def _fake_llm_client(content: str) -> Any:
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))


def test_same_pr_number_across_repos_both_survive_summarization() -> None:
    # A team digest spans repos, where PR numbers repeat. Keying by bare pr_number collapsed
    # acme/a#123 and acme/b#123 into one entry (the dict held one row) and the LLM path could only
    # represent one of them. Keying by the assigned index keeps both. If this regresses the code
    # falls back to titles, so asserting the LLM summaries survive catches the collision.
    prs = [
        _pr_stub("acme/a", 123, "A change", "https://github.com/acme/a/pull/123"),
        _pr_stub("acme/b", 123, "B change", "https://github.com/acme/b/pull/123"),
    ]
    content = json.dumps(
        {"intro": "two", "prs": [{"index": 0, "summary": "repo a change"}, {"index": 1, "summary": "repo b change"}]}
    )

    with patch("products.stamphog.backend.logic.digest.get_llm_client", return_value=_fake_llm_client(content)):
        summary = summarize_merged_prs(prs)

    assert len(summary.prs) == 2
    assert {p.url for p in summary.prs} == {
        "https://github.com/acme/a/pull/123",
        "https://github.com/acme/b/pull/123",
    }
    assert {p.summary for p in summary.prs} == {"repo a change", "repo b change"}
