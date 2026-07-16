import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from django.db import (
    Error as DatabaseError,
    transaction,
)
from django.db.models import QuerySet
from django.utils import timezone

from posthog.models.scoping import team_scope

from products.stamphog.backend.facade.enums import DigestRunStatus
from products.stamphog.backend.logic.digest import DigestSummary, summarize_merged_prs
from products.stamphog.backend.models import DigestChannel, DigestRun, PullRequest, StamphogRepoConfig
from products.stamphog.backend.tasks.digest import (
    DIGEST_LOOKBACK_DAYS,
    STALE_PENDING_RUN_MINUTES,
    _previous_run_slot,
    _reclaim_stale_pending_runs,
    send_digest_for_channel,
)
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
            team_id=team_id,
            repo_config=repo_config,
            pr_number=number,
            audience_key=AUDIENCE,
            merged_at=timezone.now(),
        )
    return str(channel.id)


@pytest.mark.parametrize(
    "slack_ts,expect_status,expect_prs_linked",
    [("1234.5", DigestRunStatus.COMPLETED, True), ("", DigestRunStatus.FAILED, False)],
    ids=["posted_run_finalized_keeps_prs", "unposted_run_reclaimed_unlinks_prs"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_reclaim_stale_pending_runs(team, slack_ts, expect_status, expect_prs_linked) -> None:
    # A worker that dies mid-run leaves a PENDING run with its PRs claimed. If it already posted to Slack
    # (slack_message_ts set), reclaim must finalize it as COMPLETED and KEEP its PRs linked so the next
    # digest doesn't re-send them. If it never posted, reclaim unlinks the PRs so they're retried.
    with team_scope(team.id):
        channel_id = _seed_channel_and_prs(team.id, pr_count=2)
        run = DigestRun.objects.for_team(team.id).create(
            team_id=team.id,
            digest_channel_id=channel_id,
            status=DigestRunStatus.PENDING,
            slack_message_ts=slack_ts,
        )
        PullRequest.objects.for_team(team.id).filter(audience_key=AUDIENCE).update(digest_run=run)
        stale = timezone.now() - timedelta(minutes=STALE_PENDING_RUN_MINUTES + 5)
        DigestRun.objects.for_team(team.id).filter(id=run.id).update(created_at=stale)

    _reclaim_stale_pending_runs()

    with team_scope(team.id):
        run.refresh_from_db()
        linked = PullRequest.objects.for_team(team.id).filter(digest_run_id=run.id).count()
        channel_last_digest_at = DigestChannel.objects.for_team(team.id).get(id=channel_id).last_digest_at
    assert run.status == expect_status
    assert (linked == 2) is expect_prs_linked
    # A finalized (actually-posted) run advances the channel's clock like a normal completion would.
    assert (channel_last_digest_at is not None) is (expect_status == DigestRunStatus.COMPLETED)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_proof_of_post_persists_metadata_for_reclaim(team) -> None:
    # Worker death between Slack accepting the message and the completion transaction: the reclaim
    # sweeper finalizes from persisted state only, so the proof-of-post write must already carry
    # pr_count/summary — or the finalized run keeps zeros while its PRs stay linked.
    with team_scope(team.id):
        channel_id = _seed_channel_and_prs(team.id, pr_count=2)

    real_atomic = transaction.atomic
    atomic_calls = {"n": 0}

    def _dying_atomic(*args: Any, **kwargs: Any):
        # Call 1 is the claim transaction; call 2 is the completion transaction — the crash window
        # under test sits right after the proof-of-post write, before the completion commits.
        atomic_calls["n"] += 1
        if atomic_calls["n"] == 2:
            raise RuntimeError("worker died before the completion transaction")
        return real_atomic(*args, **kwargs)

    with (
        patch("products.stamphog.backend.tasks.digest.summarize_merged_prs", side_effect=_summary),
        patch("products.stamphog.backend.tasks.digest.post_digest", return_value="1234.5"),
        patch("products.stamphog.backend.tasks.digest.transaction.atomic", side_effect=_dying_atomic),
    ):
        with pytest.raises(RuntimeError):
            send_digest_for_channel(digest_channel_id=channel_id, team_id=team.id)

    with team_scope(team.id):
        DigestRun.objects.for_team(team.id).update(
            created_at=timezone.now() - timedelta(minutes=STALE_PENDING_RUN_MINUTES + 5)
        )
    _reclaim_stale_pending_runs()

    with team_scope(team.id):
        run = DigestRun.objects.for_team(team.id).get()
    assert run.status == DigestRunStatus.COMPLETED
    assert run.pr_count == 2
    assert run.summary  # the summary rode along with the proof-of-post, not just the message ts


@pytest.mark.parametrize(
    "fail_times,expect_raise",
    [(2, False), (3, True)],
    ids=["retries_then_succeeds", "exhausts_and_propagates"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_proof_of_post_write_retries_transient_db_error(team, fail_times: int, expect_raise: bool) -> None:
    # The proof-of-post write is the dedup proof: once Slack accepts, only slack_message_ts stops the
    # reclaim sweeper from re-sending. A transient DB blip there must be retried (not taken at face
    # value) or it converts into a duplicate Slack post. Slack is posted exactly once regardless; if the
    # write never lands, the exception propagates with the PRs still linked to the PENDING run — the
    # existing crash-window semantics the reclaim sweeper then handles.
    channel_id = _seed_channel_and_prs(team.id, pr_count=2)
    attempts = {"n": 0}
    real_update = QuerySet.update

    def flaky_update(self: Any, **kwargs: Any) -> int:
        # Target only the proof-of-post write: it sets slack_message_ts but, unlike the completion
        # write, carries no status/posted_at.
        is_proof = "slack_message_ts" in kwargs and "status" not in kwargs and "posted_at" not in kwargs
        if is_proof:
            attempts["n"] += 1
            if attempts["n"] <= fail_times:
                raise DatabaseError("transient db blip")
        return real_update(self, **kwargs)

    post = MagicMock(return_value="1234.5")
    sleeps: list[float] = []
    with (
        patch("products.stamphog.backend.tasks.digest.post_digest", post),
        patch("products.stamphog.backend.tasks.digest.summarize_merged_prs", side_effect=_summary),
        patch("products.stamphog.backend.tasks.digest.time.sleep", side_effect=lambda s: sleeps.append(s)),
        patch.object(QuerySet, "update", flaky_update),
    ):
        if expect_raise:
            with pytest.raises(DatabaseError):
                send_digest_for_channel(digest_channel_id=channel_id, team_id=team.id)
        else:
            send_digest_for_channel(digest_channel_id=channel_id, team_id=team.id)

    assert post.call_count == 1  # Slack posted exactly once either way
    with team_scope(team.id):
        run = DigestRun.objects.get()
        linked = PullRequest.objects.filter(digest_run_id=run.id).count()
    if expect_raise:
        assert run.status == DigestRunStatus.PENDING  # never finalized
        assert linked == 2  # PRs stay linked to the PENDING run for the reclaim sweeper
        assert len(sleeps) == fail_times - 1  # slept between the 3 attempts, not after the last
    else:
        assert run.status == DigestRunStatus.COMPLETED
        assert run.pr_count == 2
        assert len(sleeps) == fail_times


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
def test_claim_is_capped_per_run_and_backlog_drains_across_runs(team) -> None:
    # An unbounded claim grows the LLM prompt and the Slack payload with the merge-burst size, and a
    # rejected oversized payload retries the identical batch forever. The claim caps per run and the
    # remainder drains on the next one.
    channel_id = _seed_channel_and_prs(team.id, pr_count=3)
    batch_sizes: list[int] = []

    def sized_summary(prs: list[PullRequest]) -> DigestSummary:
        batch_sizes.append(len(prs))
        return DigestSummary(intro="x", prs=[])

    with (
        patch("products.stamphog.backend.tasks.digest.DIGEST_MAX_PRS_PER_RUN", 2),
        patch("products.stamphog.backend.tasks.digest.post_digest", return_value="ts-1"),
        patch("products.stamphog.backend.tasks.digest.summarize_merged_prs", side_effect=sized_summary),
    ):
        send_digest_for_channel(digest_channel_id=channel_id, team_id=team.id)
        send_digest_for_channel(digest_channel_id=channel_id, team_id=team.id)

    assert batch_sizes == [2, 1]
    with team_scope(team.id):
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


@pytest.mark.parametrize(
    "now,expected",
    [
        # Wednesday 08:00 -> previous slot is Tuesday 07:00
        ("2026-07-15T08:00:00+00:00", "2026-07-14T07:00:00+00:00"),
        # Monday 08:00 -> previous slot is Friday 07:00 (weekend has no slot)
        ("2026-07-13T08:00:00+00:00", "2026-07-10T07:00:00+00:00"),
        # before today's slot -> current slot is yesterday's, previous the day before
        ("2026-07-15T06:00:00+00:00", "2026-07-13T07:00:00+00:00"),
    ],
    ids=["midweek", "monday_covers_weekend", "before_todays_slot"],
)
def test_previous_run_slot(now: str, expected: str) -> None:
    assert _previous_run_slot(datetime.fromisoformat(now)) == datetime.fromisoformat(expected)


@pytest.mark.parametrize(
    "has_history,claimed_offset,unclaimed_offset",
    [
        # first digest: only the previous cadence slot onward — a day-old backlog PR is out
        (False, timedelta(hours=19), timedelta(hours=43)),
        # established channel: wide floor for failed-run resilience, but a week+ old PR is out
        (True, timedelta(hours=43), timedelta(days=DIGEST_LOOKBACK_DAYS + 1)),
    ],
    ids=["first_digest_cadence_window", "established_channel_week_floor"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
@freeze_time("2026-07-15T08:00:00+00:00")  # a Wednesday; previous slot = Tue 07:00 UTC
def test_digest_claim_floor(team, has_history: bool, claimed_offset: timedelta, unclaimed_offset: timedelta) -> None:
    # A channel's first digest must cover only the natural cadence window (what it would have
    # received had it existed one run earlier), never an arbitrary backlog; an established channel
    # keeps the wide week floor so merges from a failed run are retried instead of aging out fast.
    with team_scope(team.id):
        repo_config = StamphogRepoConfig.objects.for_team(team.id).create(
            team_id=team.id, repository=REPO, installation_id="9001"
        )
        channel = DigestChannel.objects.for_team(team.id).create(
            team_id=team.id, audience_key=AUDIENCE, slack_integration_id=1, slack_channel_id="C1"
        )
        if has_history:
            DigestRun.objects.for_team(team.id).create(
                team_id=team.id, digest_channel=channel, status=DigestRunStatus.COMPLETED
            )
        recent = PullRequest.objects.for_team(team.id).create(
            team_id=team.id,
            repo_config=repo_config,
            pr_number=1,
            audience_key=AUDIENCE,
            merged_at=timezone.now() - claimed_offset,
        )
        old = PullRequest.objects.for_team(team.id).create(
            team_id=team.id,
            repo_config=repo_config,
            pr_number=2,
            audience_key=AUDIENCE,
            merged_at=timezone.now() - unclaimed_offset,
        )

    with (
        patch("products.stamphog.backend.tasks.digest.post_digest", return_value="ts-ok"),
        patch("products.stamphog.backend.tasks.digest.summarize_merged_prs", side_effect=_summary),
    ):
        send_digest_for_channel(digest_channel_id=str(channel.id), team_id=team.id)

    with team_scope(team.id):
        recent.refresh_from_db()
        old.refresh_from_db()
    assert recent.digest_run_id is not None  # within window -> claimed and digested
    assert old.digest_run_id is None  # outside window -> left for no one, never flooded in


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
