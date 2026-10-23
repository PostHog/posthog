import json
from datetime import UTC, date, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog import redis
from posthog.models import FileSystemViewLog
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX

from products.replay.backend.facade.today_highlights import HIGHLIGHT_SOURCES
from products.today.backend.facade.testing import highlight_context

TODAY = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
EVERY_DAY = [TODAY - timedelta(days=offset) for offset in range(10)]


@time_machine.travel(NOW, tick=False)
@patch("products.replay.backend.today_highlights.feature_enabled_or_false", return_value=True)
class TestUnwatchedSavedFilters(BaseTest):
    @parameterized.expand(
        [
            (
                "a filter with recordings left to watch",
                EVERY_DAY,
                ["a"],
                False,
                [
                    (
                        "‘Checkout errors’ has 2 recordings you haven’t watched",
                        "/replay/home?savedFilterId=chk",
                    )
                ],
            ),
            (
                "more recordings than one count holds",
                EVERY_DAY,
                ["a"],
                True,
                [
                    (
                        "‘Checkout errors’ has 2+ recordings you haven’t watched",
                        "/replay/home?savedFilterId=chk",
                    )
                ],
            ),
            ("every recording watched", EVERY_DAY, ["a", "b", "c"], False, []),
            ("Replay opened on one day only", [TODAY], [], False, []),
        ]
    )
    def test_find(
        self,
        _flag: object,
        _name: str,
        replay_days: list[date],
        watched: list[str],
        has_more: bool,
        expected: list[tuple[str, str]],
    ) -> None:
        FileSystemViewLog.objects.create(
            team=self.team, user=self.user, type="scene", ref="Replay", viewed_at=NOW, view_days=replay_days
        )
        SessionRecordingPlaylist.objects.create(
            team=self.team,
            short_id="chk",
            name="Checkout errors",
            type=SessionRecordingPlaylist.PlaylistType.FILTERS,
            created_by=self.user,
        )
        redis.get_client().set(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}chk",
            json.dumps({"session_ids": ["a", "b", "c"], "has_more": has_more, "previous_ids": ["a"]}),
        )
        for session_id in watched:
            SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id=session_id)

        (source,) = HIGHLIGHT_SOURCES
        found = source.find(highlight_context(team=self.team, user=self.user, today=TODAY))

        self.assertEqual([(item.title, item.url) for item in found.items], expected)
