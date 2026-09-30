from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import status

from products.today.backend.facade.enums import BriefingStatus, BriefingTrigger
from products.today.backend.models import DailyBriefing
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin


@patch("products.today.backend.logic.briefings.sync_connect")
class TestTodayAPI(TodayTeamScopedTestMixin, APIBaseTest):
    def _flag(self, enabled: bool):
        return patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=enabled)

    def test_flag_off_hides_the_briefing(self, _sync_connect: MagicMock) -> None:
        with self._flag(False):
            response = self.client.get(f"/api/projects/{self.team.id}/today/briefing/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not DailyBriefing.objects.for_team(self.team.id).exists()

    def test_first_open_creates_one_briefing_and_starts_generation_once(self, sync_connect: MagicMock) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        with self._flag(True):
            first = self.client.get(f"/api/projects/{self.team.id}/today/briefing/?timezone=Europe/Prague")
            second = self.client.get(f"/api/projects/{self.team.id}/today/briefing/?timezone=Europe/Prague")

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert first.json()["status"] == BriefingStatus.COLLECTING
        assert second.json()["id"] == first.json()["id"]
        rows = DailyBriefing.objects.for_team(self.team.id).filter(user_id=self.user.id)
        assert [(row.trigger, row.timezone) for row in rows] == [(BriefingTrigger.FIRST_OPEN, "Europe/Prague")]
        assert sync_connect.return_value.start_workflow.call_count == 1

    def test_opening_after_noon_starts_the_midday_edition(self, sync_connect: MagicMock) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        url = f"/api/projects/{self.team.id}/today/briefing/?timezone=Europe/Prague"
        with self._flag(True):
            # Prague is UTC+2: 09:00 and then 13:00 local time on the same day.
            with time_machine.travel(datetime(2026, 9, 30, 7, 0, tzinfo=UTC), tick=False):
                morning = self.client.get(url).json()
            with time_machine.travel(datetime(2026, 9, 30, 11, 0, tzinfo=UTC), tick=False):
                midday = self.client.get(url).json()

        assert (morning["local_day"], morning["edition"]) == ("2026-09-30", "morning")
        assert (midday["local_day"], midday["edition"]) == ("2026-09-30", "midday")
        assert morning["id"] != midday["id"]
        assert sync_connect.return_value.start_workflow.call_count == 2

    def test_refresh_is_limited_per_day(self, sync_connect: MagicMock) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        with self._flag(True):
            responses = [self.client.post(f"/api/projects/{self.team.id}/today/briefing/refresh/") for _ in range(4)]

        assert [response.status_code for response in responses] == [200, 200, 200, 429]
        assert sync_connect.return_value.start_workflow.call_count == 3

    def test_briefings_of_other_people_stay_private(self, _sync_connect: MagicMock) -> None:
        other = self._create_user("other@example.com")
        with self._flag(True):
            self.client.get(f"/api/projects/{self.team.id}/today/briefing/")
            self.client.force_login(other)
            response = self.client.get(f"/api/projects/{self.team.id}/today/briefing/")

        assert response.status_code == status.HTTP_200_OK
        assert DailyBriefing.objects.for_team(self.team.id).filter(user_id=other.id).count() == 1
        assert DailyBriefing.objects.for_team(self.team.id).count() == 2
