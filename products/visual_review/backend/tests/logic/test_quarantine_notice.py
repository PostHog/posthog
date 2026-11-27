from datetime import datetime, timedelta

import pytest
from unittest.mock import MagicMock, call, patch

from django.db.models import F
from django.utils import timezone

from posthog.ownership.paths import UNOWNED_TEAM, PathOwnership
from posthog.slack.channels import SlackChannel

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import ActorType, RunType
from products.visual_review.backend.logic import quarantine, quarantine_notice, repos, story_index
from products.visual_review.backend.models import QuarantinedIdentifier
from products.visual_review.backend.tasks.tasks import QUARANTINE_NOTICE_EXPIRY_SECONDS, QUARANTINE_NOTICE_QUIET_SECONDS
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_SOURCE_PATH = "frontend/src/scenes/Button`www.example.com`.stories.tsx"
_IDENTIFIER = "scenes-app-button--primary--light"
_INDEX = story_index.StoryIndex(
    path_by_story_id={"scenes-app-button--primary": _SOURCE_PATH, "scenes-app-button--secondary": _SOURCE_PATH}
)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestSendQuarantineNotice:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=66661, repo_full_name="org/test-notice")

    @pytest.fixture
    def post(self):
        channels = "products.visual_review.backend.logic.team_channels"
        with (
            patch("products.visual_review.backend.logic.story_index.latest_story_index", return_value=_INDEX),
            patch(
                "products.visual_review.backend.logic.owners.resolve_path_owners",
                return_value=PathOwnership(team_by_path={_SOURCE_PATH: "team-devex"}, registry={}, resolved=True),
            ) as owners,
            patch(f"{channels}.IntegrationManager") as manager,
            patch(f"{channels}.SlackIntegration") as slack,
            patch(
                f"{channels}.fetch_channel_map",
                return_value={"team-devex": SlackChannel(channel_id="C1", shared=False)},
            ) as channel_map,
            patch(f"{channels}.post_with_join", return_value="1700000000.1") as post,
        ):
            manager.slack.oauth.find.return_value = MagicMock()
            slack.return_value.client.conversations_info.return_value = {"channel": {"is_shared": False}}
            post.slack = slack
            post.owners = owners
            post.channel_map = channel_map
            yield post

    def _quarantine(
        self,
        repo,
        user,
        identifier: str = _IDENTIFIER,
        source: ActorType = ActorType.HUMAN,
        reason: str = "Animation <!channel> timing",
        expires_at: datetime | None = None,
    ) -> QuarantinedIdentifier:
        return quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier=identifier,
            run_type=RunType.STORYBOOK,
            reason=reason,
            user_id=None if source == ActorType.AUTO else user.id,
            team_id=repo.team_id,
            source=source,
            expires_at=expires_at,
            notify_owners=True,
        )

    def _age(self, repo, minutes: float) -> None:
        QuarantinedIdentifier.objects.using(WRITER_DB).filter(repo=repo).update(
            created_at=F("created_at") - timedelta(minutes=minutes)
        )

    @pytest.mark.parametrize(
        "source,reason,lead",
        [
            (ActorType.HUMAN, "Animation <!channel> timing", None),
            (
                ActorType.AUTO,
                "Flake proven: changed and unchanged in two runs of abc1234",
                "*Visual review* quarantined a story owned by you automatically, "
                "because the same code rendered it two ways. Please check.",
            ),
            (
                ActorType.AUTO,
                "Extended automatically: changed in 3 of the last 100 default-branch runs, 2 pictures",
                "*Visual review* extended the quarantine of a story owned by you automatically, "
                "because the story still renders differently on the default branch. Please check.",
            ),
        ],
    )
    def test_posts_to_the_owning_team_naming_who_quarantined(self, repo, team, user, post, source, reason, lead):
        entry = self._quarantine(repo, user, source=source, reason=reason)

        self._age(repo, 4)
        assert quarantine_notice.send_pending_notices(entry.id, team.id).posts == 1
        second = self._quarantine(
            repo, user, identifier="scenes-app-button--primary--dark", source=source, reason=reason
        )
        self._age(repo, 4)
        assert quarantine_notice.send_pending_notices(second.id, team.id).posts == 1

        assert post.channel_map.call_count == 1
        _, channel_id, blocks, text = post.call_args.args
        assert channel_id == "C1"
        if source == ActorType.AUTO:
            assert text.startswith(lead)
            assert "opened by visual review automatically" in blocks[1]["text"]["text"]
        else:
            assert text.startswith(f"*{user.first_name or user.email}* quarantined a story owned by you. Please check.")
        assert "*scenes-app-button--primary* storybook" in blocks[1]["text"]["text"]
        assert "<!channel>" not in str(blocks)
        assert blocks[2]["elements"] == [
            {"type": "plain_text", "text": f"org/test-notice · {_SOURCE_PATH}", "emoji": False}
        ]

    @pytest.mark.parametrize(
        "case",
        ["unowned", "story_absent", "lifted", "shared_since_listing", "channel_unreadable"],
    )
    def test_nothing_is_posted_without_an_owning_team_an_active_quarantine_or_an_internal_channel(
        self, repo, team, user, post, case
    ):
        if case == "unowned":
            post.owners.return_value = PathOwnership(
                team_by_path={_SOURCE_PATH: UNOWNED_TEAM}, registry={}, resolved=True
            )
        entry = self._quarantine(
            repo, user, "scenes-app-gone--primary--light" if case == "story_absent" else _IDENTIFIER
        )
        if case == "shared_since_listing":
            post.slack.return_value.client.conversations_info.return_value = {"channel": {"is_ext_shared": True}}
        if case == "channel_unreadable":
            post.slack.return_value.client.conversations_info.return_value = {"ok": True}
        if case == "lifted":
            QuarantinedIdentifier.objects.using(WRITER_DB).filter(id=entry.id).update(expires_at=timezone.now())
        self._age(repo, 4)

        assert quarantine_notice.send_pending_notices(entry.id, team.id).posts == 0
        assert post.call_count == 0

    @pytest.mark.parametrize("trigger", ["first", "last"])
    def test_a_burst_posts_once_per_team_and_author_after_it_goes_quiet(self, team, repo, user, post, trigger):
        expires_at = timezone.now() + timedelta(days=10)
        first = self._quarantine(repo, user, expires_at=expires_at)
        self._quarantine(
            repo, user, identifier="scenes-app-button--primary--dark", expires_at=expires_at + timedelta(seconds=1)
        )
        self._quarantine(repo, user, source=ActorType.AGENT, identifier="scenes-app-button--secondary--light")
        last = self._quarantine(repo, user, identifier="scenes-app-button--secondary--dark")

        assert quarantine_notice.send_pending_notices(last.id, team.id) == quarantine_notice.NoticeRun(posts=0)
        early = quarantine_notice.send_pending_notices(first.id, team.id)
        assert early.posts == 0
        assert early.recheck_in_seconds is not None
        assert 0 < early.recheck_in_seconds <= QUARANTINE_NOTICE_QUIET_SECONDS + 30
        assert post.call_count == 0

        self._age(repo, 4)
        trigger_id = first.id if trigger == "first" else last.id
        assert quarantine_notice.send_pending_notices(trigger_id, team.id).posts == 2
        assert quarantine_notice.send_pending_notices(trigger_id, team.id).posts == 0

        texts = sorted(c.args[3] for c in post.call_args_list)
        name = user.first_name or user.email
        assert texts == [
            f"*{name} (using an AI agent)* quarantined a story owned by you. Please check. scenes-app-button--secondary",
            f"*{name}* quarantined 2 stories owned by you. Please check.",
        ]

    def test_one_failing_post_does_not_cost_the_other_audiences_theirs(self, team, repo, user, post):
        self._quarantine(repo, user)
        last = self._quarantine(repo, user, source=ActorType.AGENT, identifier="scenes-app-button--secondary--light")
        self._age(repo, 4)
        post.side_effect = [RuntimeError("channel archived"), "1700000000.2"]

        assert quarantine_notice.send_pending_notices(last.id, team.id).posts == 1
        assert post.call_count == 2

    @pytest.mark.parametrize("oldest_age_minutes,posts", [(1, 0), (11, 1)])
    def test_a_long_stream_posts_once_the_oldest_notice_waited_too_long(
        self, team, repo, user, post, oldest_age_minutes, posts
    ):
        self._quarantine(repo, user)
        self._age(repo, oldest_age_minutes)
        newest = self._quarantine(repo, user, identifier="scenes-app-button--secondary--light")

        assert quarantine_notice.send_pending_notices(newest.id, team.id).posts == posts

    def test_a_stale_pending_row_is_dropped_and_does_not_end_the_next_burst_early(self, team, repo, user, post):
        self._quarantine(repo, user, identifier="scenes-app-button--secondary--light")
        self._age(repo, 60)
        fresh = self._quarantine(repo, user)

        assert quarantine_notice.send_pending_notices(fresh.id, team.id).posts == 0
        self._age(repo, 4)
        assert quarantine_notice.send_pending_notices(fresh.id, team.id).posts == 1
        assert "scenes-app-button--secondary" not in str(post.call_args_list)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestDailyLimitNotice:
    @pytest.mark.parametrize("product_owner,posts", [("team-devex", 1), (UNOWNED_TEAM, 0)])
    def test_goes_to_whoever_owns_visual_review(self, team, product_owner, posts):
        repo = repos.create_repo(team_id=team.id, repo_external_id=66663, repo_full_name="org/test-limit")
        channels = "products.visual_review.backend.logic.team_channels"
        notice = "products.visual_review.backend.logic.quarantine_notice"
        with (
            patch(f"{notice}.fetcher_for_team"),
            patch(
                f"{notice}.resolve_path_owners",
                return_value=PathOwnership(
                    team_by_path={"products/visual_review/": product_owner}, registry={}, resolved=True
                ),
            ),
            patch(f"{channels}.IntegrationManager") as manager,
            patch(f"{channels}.SlackIntegration") as slack,
            patch(
                f"{channels}.fetch_channel_map",
                return_value={"team-devex": SlackChannel(channel_id="C1", shared=False)},
            ),
            patch(f"{channels}.post_with_join", return_value="1700000000.1") as post,
        ):
            manager.slack.oauth.find.return_value = MagicMock()
            slack.return_value.client.conversations_info.return_value = {"channel": {"is_shared": False}}
            quarantine_notice.send_daily_limit_notice(repo.id, team.id, 10)

        assert post.call_count == posts
        if posts:
            assert post.call_args.args[3].startswith(
                "Visual review quarantined 10 stories automatically in org/test-limit in the last 24 hours. "
                "The capture harness may have regressed."
            )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestQuarantineDispatchesNotice:
    @pytest.mark.parametrize(
        "notify_owners,broker_error",
        [(True, None), (False, None), (True, ConnectionError("broker down"))],
    )
    def test_the_notice_is_queued_only_when_asked_for_and_never_fails_the_quarantine(
        self, team, user, django_capture_on_commit_callbacks, notify_owners, broker_error
    ):
        repo = repos.create_repo(team_id=team.id, repo_external_id=66662, repo_full_name="org/test-dispatch")
        with (
            patch(
                "products.visual_review.backend.tasks.tasks.notify_quarantine_owners.apply_async",
                side_effect=broker_error,
            ) as apply_async,
            django_capture_on_commit_callbacks(using=WRITER_DB, execute=True),
        ):
            entry = quarantine.quarantine_identifier(
                repo_id=repo.id,
                identifier=_IDENTIFIER,
                run_type=RunType.STORYBOOK,
                reason="flaky",
                user_id=user.id,
                team_id=team.id,
                notify_owners=notify_owners,
            )

        expected = [
            call(
                args=(team.id, str(entry.id)),
                countdown=QUARANTINE_NOTICE_QUIET_SECONDS,
                expires=QUARANTINE_NOTICE_QUIET_SECONDS + QUARANTINE_NOTICE_EXPIRY_SECONDS,
            )
        ]
        assert apply_async.call_args_list == (expected if notify_owners else [])
        stored = QuarantinedIdentifier.objects.using(WRITER_DB).get(id=entry.id)
        assert stored.owner_notice_pending is notify_owners
