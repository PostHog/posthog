import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from django.db import OperationalError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from parameterized import parameterized
from posthog_owners.schema import TeamEntry
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.stamphog.backend.facade.enums import AudienceReason, ChannelResolutionSource, DigestRunStatus
from products.stamphog.backend.logic.channel_resolution import (
    Destination,
    RoutingContext,
    RoutingUnavailable,
    SlackChannel,
)
from products.stamphog.backend.logic.digest import (
    MAX_DIGEST_PRS,
    DigestPRSummary,
    DigestSummary,
    _capped_summary,
    _parse_llm_response,
    summarize_merged_prs,
)
from products.stamphog.backend.logic.digest_runs import (
    DIGEST_LOOKBACK_DAYS,
    STALE_PENDING_RUN_MINUTES,
    _previous_run_slot,
    pending_audiences_by_team,
    reclaim_stale_pending_runs,
)
from products.stamphog.backend.logic.slack_digest import DigestSlackError, post_digest_details, post_digest_lead
from products.stamphog.backend.models import DigestRun, PullRequest, PullRequestAudience, StamphogRepoConfig
from products.stamphog.backend.tasks.digest import send_team_digests
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES
from products.stamphog.backend.tests.fakes import FakeSlackIntegration

REPO = "acme/widgets"
AUDIENCE = "team-devex"


def _summary(prs: list[PullRequest], audiences: list | None = None) -> DigestSummary:
    """Stand in for the LLM so the task never reaches a gateway. Keeps every PR: a summary that
    keeps nothing is its own path (the digest posts nothing and releases the claim).

    Goes through _capped_summary rather than building a DigestSummary, so a task test sees the same
    truncation a real run would."""
    return _capped_summary(
        len(prs),
        [
            DigestPRSummary(
                pr_number=pr.pr_number,
                title=pr.title,
                url=pr.pr_url,
                author_login=pr.author_login,
                summary=pr.title,
                repository=pr.repo_config.repository,
            )
            for pr in prs
        ],
    )


def _seed_prs(
    team_id: int,
    pr_count: int = 2,
    repository: str = REPO,
    first_number: int = 1,
    digest_enabled: bool = True,
) -> StamphogRepoConfig:
    repo_config = StamphogRepoConfig.objects.for_team(team_id).create(
        team_id=team_id, repository=repository, installation_id="9001", digest_enabled=digest_enabled
    )
    for number in range(first_number, first_number + pr_count):
        pr = PullRequest.objects.for_team(team_id).create(
            team_id=team_id,
            repo_config=repo_config,
            pr_number=number,
            title=f"Change number {number}",
            author_login="devex-dev",
            pr_url=f"https://github.com/{repository}/pull/{number}",
            merged_at=timezone.now(),
        )
        PullRequestAudience.objects.for_team(team_id).create(
            team_id=team_id, pull_request=pr, audience_key=AUDIENCE, reason=AudienceReason.OWNED
        )
    return repo_config


def _channel(channel_id: str, shared: bool = False) -> SlackChannel:
    return SlackChannel(channel_id=channel_id, shared=shared)


def _routing_context(
    registry_by_repo: dict[str, dict[str, TeamEntry]] | None = None,
    declared_repo_channel: dict[str, str] | None = None,
    channels_by_name: dict[str, SlackChannel] | None = None,
) -> RoutingContext:
    """A routing context built in memory, so a task test never reaches GitHub or Slack.

    The default routes AUDIENCE to C1 through the plain name match, which is what most of these
    tests want: they are about claiming and posting, not about how the destination was decided.
    """
    return RoutingContext(
        slack_integration_id=1,
        registry_by_repo=registry_by_repo if registry_by_repo is not None else {REPO: {}},
        inherited_registry=next((r for r in (registry_by_repo or {}).values() if r), {}),
        declared_repo_channel=declared_repo_channel or {},
        channels_by_name=channels_by_name if channels_by_name is not None else {AUDIENCE: _channel("C1")},
    )


def _run_digests(team_id: int, context: RoutingContext | None = None) -> None:
    with patch(
        "products.stamphog.backend.logic.digest_runs.build_routing_context",
        return_value=_routing_context() if context is None else context,
    ):
        send_team_digests(team_id=team_id, audience_keys=[AUDIENCE])


@pytest.mark.parametrize(
    "slack_ts,expect_status,expect_prs_linked",
    [("1234.5", DigestRunStatus.COMPLETED, True), ("", DigestRunStatus.FAILED, False)],
    ids=["posted_run_finalized_keeps_prs", "unposted_run_reclaimed_unlinks_prs"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def testreclaim_stale_pending_runs(team, slack_ts, expect_status, expect_prs_linked) -> None:
    # A worker that dies mid-run leaves a PENDING run with its PRs claimed. If it already posted to Slack
    # (slack_message_ts set), reclaim must finalize it as COMPLETED and KEEP its PRs linked so the next
    # digest doesn't re-send them. If it never posted, reclaim unlinks the PRs so they're retried.
    with team_scope(team.id):
        _seed_prs(team.id, pr_count=2)
        run = DigestRun.objects.for_team(team.id).create(
            team_id=team.id,
            audience_key=AUDIENCE,
            slack_channel_id="C1",
            status=DigestRunStatus.PENDING,
            slack_message_ts=slack_ts,
        )
        PullRequestAudience.objects.for_team(team.id).filter(audience_key=AUDIENCE).update(digest_run=run)
        stale = timezone.now() - timedelta(minutes=STALE_PENDING_RUN_MINUTES + 5)
        DigestRun.objects.for_team(team.id).filter(id=run.id).update(created_at=stale)

    reclaim_stale_pending_runs()

    with team_scope(team.id):
        run.refresh_from_db()
        linked = PullRequestAudience.objects.for_team(team.id).filter(digest_run_id=run.id).count()
    assert run.status == expect_status
    assert (linked == 2) is expect_prs_linked


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_proof_of_post_persists_metadata_for_reclaim(team) -> None:
    # Worker death between Slack accepting the message and the completion transaction: the reclaim
    # sweeper finalizes from persisted state only, so the proof-of-post write must already carry
    # pr_count/summary — or the finalized run keeps zeros while its PRs stay linked.
    with team_scope(team.id):
        _seed_prs(team.id, pr_count=2)

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
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="1234.5"),
        patch("products.stamphog.backend.logic.digest_runs.transaction.atomic", side_effect=_dying_atomic),
    ):
        # send_team_digests contains each audience's failure, so the crash is read off the run state
        # rather than raised out of the task.
        _run_digests(team.id)

    with team_scope(team.id):
        DigestRun.objects.for_team(team.id).update(
            created_at=timezone.now() - timedelta(minutes=STALE_PENDING_RUN_MINUTES + 5)
        )
    reclaim_stale_pending_runs()

    with team_scope(team.id):
        run = DigestRun.objects.for_team(team.id).get()
    assert run.status == DigestRunStatus.COMPLETED
    assert run.pr_count == 2
    assert run.summary  # the summary rode along with the proof-of-post, not just the message ts


@pytest.mark.parametrize(
    "fail_times,expect_pending",
    [(2, False), (3, True)],
    ids=["retries_then_succeeds", "exhausts_and_leaves_the_run_for_the_sweeper"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_proof_of_post_write_retries_transient_db_error(team, fail_times: int, expect_pending: bool) -> None:
    # The proof-of-post write is the dedup proof: once Slack accepts, only slack_message_ts stops the
    # reclaim sweeper from re-sending. A transient DB blip there must be retried (not taken at face
    # value) or it converts into a duplicate Slack post. Slack is posted exactly once regardless; if the
    # write never lands, the run stays PENDING with its PRs linked — the crash-window semantics the
    # reclaim sweeper then handles.
    _seed_prs(team.id, pr_count=2)
    attempts = {"n": 0}
    real_update = QuerySet.update

    def flaky_update(self: Any, **kwargs: Any) -> int:
        # Target only the proof-of-post write: it sets slack_message_ts but, unlike the completion
        # write, carries no status/posted_at.
        is_proof = "slack_message_ts" in kwargs and "status" not in kwargs and "posted_at" not in kwargs
        if is_proof:
            attempts["n"] += 1
            if attempts["n"] <= fail_times:
                raise OperationalError("transient db blip")
        return real_update(self, **kwargs)

    post = MagicMock(return_value="1234.5")
    sleeps: list[float] = []
    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", post),
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
        patch("products.stamphog.backend.logic.digest_runs.time.sleep", side_effect=lambda s: sleeps.append(s)),
        patch.object(QuerySet, "update", flaky_update),
    ):
        _run_digests(team.id)

    assert post.call_count == 1  # Slack posted exactly once either way
    with team_scope(team.id):
        run = DigestRun.objects.get()
        linked = PullRequestAudience.objects.filter(digest_run_id=run.id).count()
    if expect_pending:
        assert run.status == DigestRunStatus.PENDING  # never finalized
        assert linked == 2  # PRs stay linked to the PENDING run for the reclaim sweeper
        assert len(sleeps) == fail_times - 1  # slept between the 3 attempts, not after the last
    else:
        assert run.status == DigestRunStatus.COMPLETED
        assert run.pr_count == 2
        assert len(sleeps) == fail_times


# ---- Finding 2: an audience's digest must never post to Slack twice ----------------------------


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_concurrent_runs_for_one_audience_post_to_slack_once(team) -> None:
    # Two workers firing for the same audience would both read the same unlinked PRs and both post.
    # The fix claims the PRs (links them to a run) before posting, so a second worker that starts
    # mid-post finds nothing unlinked and returns without posting. Re-entering post_digest simulates
    # that overlap deterministically.
    _seed_prs(team.id)
    posts: list[str] = []

    def reentrant_post(team_id: int, destination: Any, summary: Any) -> str:
        posts.append(destination.channel_id)
        if len(posts) == 1:  # a second worker starts while the first is posting
            _run_digests(team_id)
        return f"ts-{len(posts)}"

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", side_effect=reentrant_post),
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id)

    assert len(posts) == 1  # the re-entrant worker found no unlinked PRs and did not post
    with team_scope(team.id):
        completed = list(DigestRun.objects.filter(status=DigestRunStatus.COMPLETED))
        assert len(completed) == 1
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_two_repos_declaring_one_team_partition_rather_than_duplicate(team) -> None:
    # A repo declaring a team's channel is a scope, not a conflict: it answers for its own merges
    # and leaves everyone else's alone. Picking a winner discards a declaration somebody wrote, and
    # fanning out posts every merge twice in the product whose problem is volume. Each PR must
    # appear in exactly one digest.
    _seed_prs(team.id, pr_count=2, repository=REPO, first_number=1)
    _seed_prs(team.id, pr_count=3, repository="acme/gadgets", first_number=10)
    context = _routing_context(
        registry_by_repo={
            # REPO carries a registry that does not mention this team, which is an answer: the
            # derived name is right. Without that, gadgets' declaration would capture REPO's merges
            # too, since REPO declared nothing to the contrary.
            REPO: {"team-other": TeamEntry(slack="#team-other")},
            "acme/gadgets": {AUDIENCE: TeamEntry(notifications="#bots-devex")},
        },
        channels_by_name={AUDIENCE: _channel("C1"), "bots-devex": _channel("C2")},
    )
    posted: dict[str, int] = {}

    def record(team_id: int, destination: Any, summary: Any) -> str:
        posted[destination.channel_id] = len(summary.prs)
        return f"ts-{destination.channel_id}"

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", side_effect=record),
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id, context)

    assert posted == {"C1": 2, "C2": 3}
    with team_scope(team.id):
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == 0
        sources = set(DigestRun.objects.values_list("resolution_source", flat=True))
    assert sources == {ChannelResolutionSource.SLACK_NAME_MATCH, ChannelResolutionSource.OWNERS_CONTACT}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_switching_a_repos_digest_off_stops_merges_it_already_captured(team) -> None:
    # The toggle used to be read only at capture, which decides what gets stamped. A repo switched
    # off after its merges landed therefore kept posting them for the rest of the claim window, and
    # the owner who switched it off had no way to stop that. Reading it at claim time is what makes
    # the toggle take effect on the next digest rather than on the next merge.
    repo_config = _seed_prs(team.id, pr_count=3)
    with team_scope(team.id):
        StamphogRepoConfig.objects.filter(id=repo_config.id).update(digest_enabled=False)

    assert pending_audiences_by_team().get(team.id) is None

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="ts-1") as post,
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id)
    assert not post.called
    with team_scope(team.id):
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == 3

    # Switching it back on returns the backlog still inside the claim floor, rather than losing it.
    with team_scope(team.id):
        StamphogRepoConfig.objects.filter(id=repo_config.id).update(digest_enabled=True)
    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="ts-1") as post,
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id)
    assert post.called
    with team_scope(team.id):
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_unroutable_merges_do_not_starve_routable_ones_behind_them(team) -> None:
    # The cap used to be applied before routing. An audience whose oldest merges all came from an
    # unroutable repo filled the whole claim with rows the run then dropped, and because dropped
    # rows stay unclaimed the next run selected exactly the same ones. The routable merges behind
    # them were never reached and aged out of the window unposted.
    _seed_prs(team.id, pr_count=2, repository="acme/nowhere", first_number=1)
    _seed_prs(team.id, pr_count=2, repository=REPO, first_number=10)
    context = _routing_context(
        registry_by_repo={REPO: {}},  # acme/nowhere is not a candidate repo, so it routes nowhere
        channels_by_name={AUDIENCE: _channel("C1")},
    )

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="ts-1") as post,
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
        patch("products.stamphog.backend.logic.digest_runs.DIGEST_MAX_PRS_PER_RUN", 2),
    ):
        _run_digests(team.id, context)

    assert post.called
    _team_id, _destination, posted = post.call_args.args
    assert {pr.pr_number for pr in posted.prs} == {10, 11}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_repo_with_no_registry_inherits_one(team) -> None:
    # The convenience layer. charts carries no ownership file at all, so a team whose channel is not
    # named after its slug still routes correctly there because the monorepo says where it goes.
    _seed_prs(team.id, pr_count=2, repository="acme/charts")
    context = _routing_context(
        registry_by_repo={"acme/charts": {}, REPO: {AUDIENCE: TeamEntry(slack="#team-apm")}},
        channels_by_name={"team-apm": _channel("C9")},
    )
    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="ts-1") as post,
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id, context)

    _team_id, destination, _posted = post.call_args.args
    assert destination.channel_id == "C9"


@pytest.mark.parametrize(
    "context_kwargs,reason",
    [
        ({"registry_by_repo": {REPO: {AUDIENCE: TeamEntry(notifications=False)}}}, "silenced_by_config"),
        ({"channels_by_name": {}}, "no_channel_of_that_name"),
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_unroutable_merges_stay_unclaimed(team, context_kwargs: dict, reason: str) -> None:
    # Claiming marks a PR as handled forever, so a merge that routes nowhere must not be claimed.
    # A team that silences its digest today and declares a channel next week has to receive the
    # merges in between, and a channel created after the declaration has to pick up the backlog.
    _seed_prs(team.id, pr_count=2)

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead") as post,
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id, _routing_context(**context_kwargs))

    assert not post.called
    with team_scope(team.id):
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == 2
        assert not DigestRun.objects.exists()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_an_unreadable_registry_posts_nothing(team) -> None:
    # Routing is derived every run and never cached, so a half-read registry does not degrade — it
    # silently reroutes. The repo whose fetch failed could be the one declaring every team's
    # channel, and continuing without it would send a whole morning of digests to derived names.
    _seed_prs(team.id, pr_count=2)

    with (
        patch(
            "products.stamphog.backend.logic.digest_runs.build_routing_context",
            side_effect=RoutingUnavailable("github is down"),
        ),
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead") as post,
    ):
        send_team_digests(team_id=team.id, audience_keys=[AUDIENCE])

    assert not post.called
    with team_scope(team.id):
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == 2


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_claim_is_capped_per_run_and_backlog_drains_across_runs(team) -> None:
    # An unbounded claim grows the LLM prompt and the Slack payload with the merge-burst size, and a
    # rejected oversized payload retries the identical batch forever. The claim caps per run and the
    # remainder drains on the next one.
    _seed_prs(team.id, pr_count=3)
    batch_sizes: list[int] = []

    def sized_summary(prs: list[PullRequest], audiences: list | None = None) -> DigestSummary:
        batch_sizes.append(len(prs))
        return _summary(prs)

    with (
        patch("products.stamphog.backend.logic.digest_runs.DIGEST_MAX_PRS_PER_RUN", 2),
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="ts-1"),
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=sized_summary),
    ):
        _run_digests(team.id)
        _run_digests(team.id)

    assert batch_sizes == [2, 1]
    with team_scope(team.id):
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_prs_the_cap_left_out_come_back_next_run(team) -> None:
    # Claiming marks every PR in a run as handled, so a PR the cap truncates is consumed by a
    # digest that never showed it and no later digest can reach it. The overflow has to go back to
    # unclaimed, while the PRs the summarizer deliberately left out stay consumed.
    overflow = 2
    _seed_prs(team.id, pr_count=MAX_DIGEST_PRS + overflow)

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="ts-1") as post,
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id)

    assert post.called
    _team_id, _destination, posted = post.call_args.args
    assert len(posted.prs) == MAX_DIGEST_PRS
    with team_scope(team.id):
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == overflow
        assert PullRequestAudience.objects.filter(digest_run__isnull=False).count() == MAX_DIGEST_PRS


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_failed_slack_post_leaves_prs_retryable_next_run(team) -> None:
    # A Slack failure must not hide the PRs: they're claimed before posting, so on failure they have
    # to be unlinked again (the retry query filters digest_run__isnull=True). Otherwise they'd stay
    # bound to a FAILED run and never retry.
    _seed_prs(team.id)

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", side_effect=RuntimeError("slack down")),
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id)

    with team_scope(team.id):
        run = DigestRun.objects.get()
        assert run.status == DigestRunStatus.FAILED
        assert PullRequestAudience.objects.filter(digest_run__isnull=True).count() == 2  # unlinked, retryable

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="ts-ok"),
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id)

    with team_scope(team.id):
        completed = DigestRun.objects.get(status=DigestRunStatus.COMPLETED)
        assert PullRequestAudience.objects.filter(digest_run=completed).count() == 2  # retry picked them up


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
    ids=["first_digest_cadence_window", "established_audience_week_floor"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
@freeze_time("2026-07-15T08:00:00+00:00")  # a Wednesday; previous slot = Tue 07:00 UTC
def test_digest_claim_floor(team, has_history: bool, claimed_offset: timedelta, unclaimed_offset: timedelta) -> None:
    # An audience's first digest must cover only the natural cadence window (what it would have
    # received had it been routable one run earlier), never an arbitrary backlog; an established
    # audience keeps the wide week floor so merges from a failed run are retried instead of aging
    # out fast.
    with team_scope(team.id):
        repo_config = StamphogRepoConfig.objects.for_team(team.id).create(
            team_id=team.id, repository=REPO, installation_id="9001", digest_enabled=True
        )
        if has_history:
            DigestRun.objects.for_team(team.id).create(
                team_id=team.id,
                audience_key=AUDIENCE,
                slack_channel_id="C1",
                status=DigestRunStatus.COMPLETED,
            )
        recent = PullRequestAudience.objects.for_team(team.id).create(
            team_id=team.id,
            pull_request=PullRequest.objects.for_team(team.id).create(
                team_id=team.id,
                repo_config=repo_config,
                pr_number=1,
                merged_at=timezone.now() - claimed_offset,
            ),
            audience_key=AUDIENCE,
            reason=AudienceReason.OWNED,
        )
        old = PullRequestAudience.objects.for_team(team.id).create(
            team_id=team.id,
            pull_request=PullRequest.objects.for_team(team.id).create(
                team_id=team.id,
                repo_config=repo_config,
                pr_number=2,
                merged_at=timezone.now() - unclaimed_offset,
            ),
            audience_key=AUDIENCE,
            reason=AudienceReason.OWNED,
        )

    with (
        patch("products.stamphog.backend.logic.digest_runs.post_digest_lead", return_value="ts-ok"),
        patch("products.stamphog.backend.logic.digest_runs.summarize_merged_prs", side_effect=_summary),
    ):
        _run_digests(team.id)

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
    content = json.dumps({"prs": [{"index": 0, "summary": "repo a change"}, {"index": 1, "summary": "repo b change"}]})

    with patch("products.stamphog.backend.logic.digest.get_llm_client", return_value=_fake_llm_client(content)):
        summary = summarize_merged_prs(prs)

    assert len(summary.prs) == 2
    assert {p.url for p in summary.prs} == {
        "https://github.com/acme/a/pull/123",
        "https://github.com/acme/b/pull/123",
    }
    assert {p.summary for p in summary.prs} == {"repo a change", "repo b change"}


@parameterized.expand(
    [
        ("empty_list_is_intentional_filtering", '{"prs": []}', True),
        ("unrecognizable_entries_are_not", '{"prs": [{"index": 99}, "junk"]}', False),
        ("missing_key_is_not", '{"summary": "x"}', False),
    ]
)
def test_only_a_genuinely_empty_result_posts_nothing(_name: str, content: str, accepted: bool) -> None:
    # Keeping nothing is a real answer for an owning team. A list we could read no PR out of is a
    # broken response wearing that shape, and accepting it would consume every claimed audience for
    # an empty post instead of falling back to the deterministic list.
    prs_by_index = {0: _pr_stub("PostHog/posthog", 1, "Title", "https://example.com/1")}
    if accepted:
        assert _parse_llm_response(content, prs_by_index).prs == []
    else:
        with pytest.raises(ValueError):
            _parse_llm_response(content, prs_by_index)


@pytest.mark.parametrize(
    "raw_headline,expected",
    [
        ("The scanner stops at 24 months.", "The scanner stops at 24 months."),
        ("  The scanner stops.\n\n It also logs.  ", "The scanner stops. It also logs."),
        ("- The scanner stops.\n- It also logs.", "- The scanner stops. - It also logs."),
        ("See https://github.com/o/r/pull/1 for the change.", ""),
        ("<https://github.com/o/r/pull/1|The scanner stops.>", ""),
        (["not", "a", "string"], ""),
    ],
    ids=[
        "a_plain_paragraph_survives",
        "line_breaks_collapse_into_one_paragraph",
        "a_list_collapses_rather_than_reaching_the_channel_as_lines",
        "a_bare_url_drops_the_whole_headline",
        "a_slack_link_drops_the_whole_headline",
        "a_non_string_drops_the_whole_headline",
    ],
)
def test_the_headline_reaches_the_channel_as_one_link_free_paragraph(raw_headline: Any, expected: str) -> None:
    # The headline is the only part posted where a reader cannot choose to skip it, and it is meant
    # to read as prose. A model that answers with bullets puts the list back in the channel, and one
    # that answers with a URL either shows a raw link mid-sentence or, once escaped, shows raw
    # markup. Neither is repairable in place, so a link drops the headline and the renderer leads
    # with the scope line instead.
    content = json.dumps({"headline": raw_headline, "prs": [{"index": 0, "summary": "Ship it."}]})
    summary = _parse_llm_response(content, {0: _pr_stub("o/r", 1, "Ship it", "https://example.com/1")})
    assert summary.headline == expected
    # A rejected headline never costs the change line it was written over.
    assert len(summary.prs) == 1


def _slack_destination(team: Any) -> Destination:
    integration = Integration.objects.create(
        team_id=team.id, kind="slack", config={}, sensitive_config={"access_token": "x"}
    )
    return Destination(
        slack_integration_id=integration.id,
        channel_id="C1",
        channel_name="team-devex",
        source=ChannelResolutionSource.SLACK_NAME_MATCH,
    )


def _one_pr_summary(headline: str = "") -> DigestSummary:
    return DigestSummary(
        considered=1,
        headline=headline,
        prs=[
            DigestPRSummary(
                pr_number=1,
                title="Add util helper",
                url="https://github.com/acme/widgets/pull/1",
                author_login="devex-dev",
                summary="Add util helper",
                repository=REPO,
            )
        ],
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_the_changes_are_posted_as_a_thread_reply_under_the_lead(team) -> None:
    # The channel gets one line and the change lines hang off it. Losing thread_ts posts those
    # lines as a second top-level message, so the channel carries more of the digest than the flat
    # version it replaced rather than less.
    destination = _slack_destination(team)
    FakeSlackIntegration.reset(channels=[])

    with patch("products.stamphog.backend.logic.slack_digest.SlackIntegration", FakeSlackIntegration):
        summary = _one_pr_summary("The util helper landed.")
        message_ts = post_digest_lead(team.id, destination, summary)
        assert message_ts == "1234.5678"
        post_digest_details(team.id, destination, summary, message_ts)

    posted = FakeSlackIntegration.posted_messages
    assert [p["thread_ts"] for p in posted] == [None, "1234.5678"]
    assert "pull/1" not in str(posted[0]["blocks"])
    assert "pull/1" in str(posted[1]["blocks"])


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_failed_thread_reply_still_counts_as_a_posted_digest(team) -> None:
    # Slack already accepted the lead, and the caller writes that ts as proof-of-post before
    # consuming the claimed PRs. Raising here would mark the run failed, unlink its PRs, and post
    # the same lead into the channel again tomorrow.
    destination = _slack_destination(team)
    FakeSlackIntegration.reset(channels=[], fail_thread_replies=True)

    with patch("products.stamphog.backend.logic.slack_digest.SlackIntegration", FakeSlackIntegration):
        summary = _one_pr_summary("The util helper landed.")
        message_ts = post_digest_lead(team.id, destination, summary)
        assert message_ts == "1234.5678"
        post_digest_details(team.id, destination, summary, message_ts)

    assert len(FakeSlackIntegration.posted_messages) == 2


def _slack_stub(post_error: str, join_error: str | None, joined: list[str]) -> MagicMock:
    """SlackIntegration stand-in whose post fails with ``post_error`` until the app has joined."""
    stub = MagicMock()

    def post(**kwargs: Any) -> dict[str, Any]:
        if not joined:
            raise SlackApiError(post_error, {"ok": False, "error": post_error})
        return {"ok": True, "ts": "9999.1"}

    def join(channel: str) -> dict[str, Any]:
        if join_error:
            # already_in_channel means somebody else already put the app in there, so the retried
            # post has to succeed — the stub records the membership before raising.
            if join_error == "already_in_channel":
                joined.append(channel)
            raise SlackApiError(join_error, {"ok": False, "error": join_error})
        joined.append(channel)
        return {"ok": True}

    stub.client.chat_postMessage.side_effect = post
    stub.client.conversations_join.side_effect = join
    return stub


@pytest.mark.parametrize(
    "post_error,join_error,expected_error,joined",
    [
        ("not_in_channel", None, None, ["C1"]),
        ("not_in_channel", "already_in_channel", None, ["C1"]),
        ("not_in_channel", "missing_scope", DigestSlackError, []),
        ("channel_not_found", None, SlackApiError, []),
    ],
    ids=[
        "joins_then_posts",
        "already_in_channel_counts_as_joined",
        "refused_join_names_the_reason_and_the_invite",
        "other_slack_errors_propagate",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_post_digest_joins_a_channel_the_app_was_never_invited_to(
    team, post_error: str, join_error: str | None, expected_error: type[Exception] | None, joined: list[str]
) -> None:
    # An auto-provisioned channel is matched off the workspace list, so the app is not a member of it
    # and the first post comes back not_in_channel. Joining is what makes that post land, and a
    # concurrent worker joining first (already_in_channel) must not fail a digest whose retry would
    # have gone through. A genuine refusal names Slack's reason and the invite, because neither is
    # derivable from an error code by the person reading the run.
    destination = _slack_destination(team)
    summary = _one_pr_summary()
    actually_joined: list[str] = []
    stub = _slack_stub(post_error, join_error, actually_joined)

    with patch("products.stamphog.backend.logic.slack_digest.SlackIntegration", return_value=stub):
        if expected_error is None:
            assert post_digest_lead(team.id, destination, summary) == "9999.1"
        else:
            with pytest.raises(expected_error) as caught:
                post_digest_lead(team.id, destination, summary)
            if expected_error is DigestSlackError:
                assert "/invite @PostHog" in str(caught.value)
                assert str(join_error) in str(caught.value)

    assert actually_joined == joined
