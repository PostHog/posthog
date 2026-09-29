from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.ownership.paths import UNOWNED_TEAM, PathOwnership
from posthog.slack.channels import SlackChannel

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import quarantine, quarantine_notice, repos, story_index
from products.visual_review.backend.logic.quarantine_notice import NoticeOutcome
from products.visual_review.backend.models import QuarantinedIdentifier
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_MODULE = "products.visual_review.backend.logic.quarantine_notice"
_SOURCE_PATH = "frontend/src/scenes/Button.stories.tsx"
_STORY_ID = "scenes-app-button--primary"
_INDEX = story_index.StoryIndex(path_by_story_id={_STORY_ID: _SOURCE_PATH})
_WORKSPACE = "T0WORKSPACE"


def _ownership(team_by_path: dict[str, str]) -> PathOwnership:
    return PathOwnership(team_by_path=team_by_path, registry={}, resolved=True)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestSendQuarantineNotice:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=66661, repo_full_name="org/test-notice")

    @pytest.fixture
    def slack(self):
        with (
            patch(f"{_MODULE}.story_index.latest_story_index", return_value=_INDEX),
            patch(f"{_MODULE}.resolve_path_owners", return_value=_ownership({_SOURCE_PATH: "team-devex"})) as owners,
            patch(f"{_MODULE}.Integration") as integration,
            patch(f"{_MODULE}.SlackIntegration") as slack_integration,
            patch(
                f"{_MODULE}.fetch_channel_map",
                return_value={"team-devex": SlackChannel(channel_id="C1", shared=False)},
            ),
            patch(f"{_MODULE}.post_with_join", return_value="1700000000.1") as post,
        ):
            integration.objects.filter.return_value.first.return_value = MagicMock(integration_id=_WORKSPACE)
            client = slack_integration.return_value.client
            client.users_lookupByEmail.return_value = {"user": {"id": "U42", "team_id": _WORKSPACE}}
            yield MagicMock(post=post, owners=owners, client=client)

    def _quarantine(self, repo, user, identifier: str = f"{_STORY_ID}--light", expires_in: timedelta | None = None):
        return quarantine.quarantine_identifier(
            repo_id=repo.id,
            identifier=identifier,
            run_type=RunType.STORYBOOK,
            reason="Animation <!channel> timing",
            user_id=user.id,
            team_id=repo.team_id,
            expires_at=timezone.now() + expires_in if expires_in is not None else None,
        )

    def test_posts_to_the_owning_team_naming_who_quarantined_once_per_story(self, repo, team, user, slack):
        light = self._quarantine(repo, user)
        dark = self._quarantine(repo, user, identifier=f"{_STORY_ID}--dark")

        assert quarantine_notice.send_quarantine_notice(light.id, team.id) == NoticeOutcome.SENT
        assert quarantine_notice.send_quarantine_notice(dark.id, team.id) == NoticeOutcome.DUPLICATE

        assert slack.post.call_count == 1
        _, channel_id, blocks, text = slack.post.call_args.args
        assert channel_id == "C1"
        assert text.startswith("<@U42> quarantined a story owned by you. Please check.")
        assert _STORY_ID in blocks[1]["text"]["text"]
        assert "<!channel>" not in str(blocks)

    @pytest.mark.parametrize(
        "team_by_path,identifier,expected",
        [
            ({_SOURCE_PATH: UNOWNED_TEAM}, f"{_STORY_ID}--light", NoticeOutcome.UNOWNED),
            ({}, "scenes-app-gone--primary--light", NoticeOutcome.NOT_ATTRIBUTABLE),
        ],
    )
    def test_nothing_is_posted_when_no_team_owns_the_story(
        self, repo, team, user, slack, team_by_path, identifier, expected
    ):
        slack.owners.return_value = _ownership(team_by_path)
        entry = self._quarantine(repo, user, identifier=identifier)

        assert quarantine_notice.send_quarantine_notice(entry.id, team.id) == expected
        assert slack.post.call_count == 0

    def test_a_quarantine_lifted_before_the_notice_goes_is_not_posted(self, repo, team, user, slack):
        entry = self._quarantine(repo, user)
        QuarantinedIdentifier.objects.using(WRITER_DB).filter(id=entry.id).update(expires_at=timezone.now())

        assert quarantine_notice.send_quarantine_notice(entry.id, team.id) == NoticeOutcome.ENTRY_INACTIVE
        assert slack.post.call_count == 0

    def test_a_slack_user_from_another_workspace_is_named_not_mentioned(self, repo, team, user, slack):
        slack.client.users_lookupByEmail.return_value = {"user": {"id": "U99", "team_id": "T0OTHER"}}
        entry = self._quarantine(repo, user)

        quarantine_notice.send_quarantine_notice(entry.id, team.id)

        text = slack.post.call_args.args[3]
        assert "<@U99>" not in text
        assert text.startswith(f"*{user.first_name or user.email}* quarantined a story owned by you.")


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestQuarantineDispatchesNotice:
    @pytest.mark.parametrize("notify_owners,dispatched", [(True, 1), (False, 0)])
    def test_the_notice_is_queued_only_when_asked_for(
        self, team, user, django_capture_on_commit_callbacks, notify_owners, dispatched
    ):
        repo = repos.create_repo(team_id=team.id, repo_external_id=66662, repo_full_name="org/test-dispatch")
        with (
            patch("products.visual_review.backend.tasks.tasks.notify_quarantine_owners.delay") as delay,
            django_capture_on_commit_callbacks(using=WRITER_DB, execute=True),
        ):
            entry = quarantine.quarantine_identifier(
                repo_id=repo.id,
                identifier=f"{_STORY_ID}--light",
                run_type=RunType.STORYBOOK,
                reason="flaky",
                user_id=user.id,
                team_id=team.id,
                notify_owners=notify_owners,
            )

        assert delay.call_count == dispatched
        if dispatched:
            delay.assert_called_once_with(team.id, str(entry.id))
