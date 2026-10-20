import pytest
from unittest.mock import MagicMock, call, patch

from django.utils import timezone

from posthog.ownership.paths import UNOWNED_TEAM, PathOwnership
from posthog.slack.channels import SlackChannel

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import quarantine, quarantine_notice, repos, story_index
from products.visual_review.backend.models import QuarantinedIdentifier
from products.visual_review.backend.tasks.tasks import QUARANTINE_NOTICE_EXPIRY_SECONDS
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_SOURCE_PATH = "frontend/src/scenes/Button`www.example.com`.stories.tsx"
_IDENTIFIER = "scenes-app-button--primary--light"
_INDEX = story_index.StoryIndex(path_by_story_id={"scenes-app-button--primary": _SOURCE_PATH})


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
            patch(f"{channels}.Integration") as integration,
            patch(f"{channels}.SlackIntegration") as slack,
            patch(
                f"{channels}.fetch_channel_map",
                return_value={"team-devex": SlackChannel(channel_id="C1", shared=False)},
            ) as channel_map,
            patch(f"{channels}.post_with_join", return_value="1700000000.1") as post,
        ):
            integration.objects.filter.return_value.first.return_value = MagicMock()
            slack.return_value.client.conversations_info.return_value = {"channel": {"is_shared": False}}
            post.slack = slack
            post.owners = owners
            post.channel_map = channel_map
            yield post

    def _quarantine(self, repo, user, identifier: str = _IDENTIFIER) -> QuarantinedIdentifier:
        return quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier=identifier,
            run_type=RunType.STORYBOOK,
            reason="Animation <!channel> timing",
            user_id=user.id,
            team_id=repo.team_id,
        )

    def test_posts_to_the_owning_team_naming_who_quarantined(self, repo, team, user, post):
        entry = self._quarantine(repo, user)

        assert quarantine_notice.send_quarantine_notice(entry.id, team.id) is True
        second = self._quarantine(repo, user, identifier="scenes-app-button--primary--dark")
        assert quarantine_notice.send_quarantine_notice(second.id, team.id) is True

        assert post.channel_map.call_count == 1
        _, channel_id, blocks, text = post.call_args.args
        assert channel_id == "C1"
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

        assert quarantine_notice.send_quarantine_notice(entry.id, team.id) is False
        assert post.call_count == 0


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

        expected = [call(args=(team.id, str(entry.id)), expires=QUARANTINE_NOTICE_EXPIRY_SECONDS)]
        assert apply_async.call_args_list == (expected if notify_owners else [])
        assert QuarantinedIdentifier.objects.using(WRITER_DB).filter(id=entry.id).exists()
