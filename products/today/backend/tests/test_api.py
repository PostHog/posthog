from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.today.backend.facade.enums import BriefingStatus, BriefingTrigger
from products.today.backend.logic import briefings
from products.today.backend.models import DailyBriefing
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin


@patch("products.today.backend.logic.briefings.sync_connect")
class TestTodayAPI(TodayTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _flag(self, enabled: bool):
        return patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=enabled)

    @parameterized.expand(
        [
            ("flag off", False, True, False),
            ("ai data processing not approved", True, False, False),
            ("out of ai credits", True, True, True),
        ]
    )
    # The class-level patch passes its mock before the parameterized arguments.
    def test_no_briefing_and_no_row_for_people_who_may_not_get_one(
        self, _sync_connect: MagicMock, _name: str, flag: bool, approved: bool, limited: bool
    ) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        with (
            self._flag(flag),
            patch("products.today.backend.feature_flags.is_team_limited", return_value=limited),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/today/briefing/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not DailyBriefing.objects.for_team(self.team.id).exists()

    def test_first_open_creates_one_briefing_and_starts_generation_once(self, sync_connect: MagicMock) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        # At noon UTC it is past eight in Prague and in the project's UTC, so both calls read the same briefing day.
        with self._flag(True), time_machine.travel(datetime(2026, 9, 30, 12, 0, tzinfo=UTC), tick=False):
            first = self.client.get(f"/api/projects/{self.team.id}/today/briefing/?timezone=Europe/Prague")
            # An MCP call sends no timezone; it must not move the person's mornings to the project's.
            second = self.client.get(f"/api/projects/{self.team.id}/today/briefing/")

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert first.json()["status"] == BriefingStatus.COLLECTING
        assert second.json()["id"] == first.json()["id"]
        rows = DailyBriefing.objects.for_team(self.team.id).filter(user_id=self.user.id)
        assert [(row.trigger, row.timezone) for row in rows] == [(BriefingTrigger.FIRST_OPEN, "Europe/Prague")]
        assert sync_connect.return_value.start_workflow.call_count == 1

    def test_first_opens_racing_each_other_start_one_run(self, sync_connect: MagicMock) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        url = f"/api/projects/{self.team.id}/today/briefing/"
        real_current = briefings._current
        reads = {"count": 0}

        # Both requests read the day's rows before either wrote; only the retry sees the winner's row.
        def stale_for_both_requests(*args, **kwargs):
            reads["count"] += 1
            return None if reads["count"] <= 2 else real_current(*args, **kwargs)

        with self._flag(True), patch.object(briefings, "_current", side_effect=stale_for_both_requests):
            first = self.client.get(url)
            second = self.client.get(url)

        assert second.json()["id"] == first.json()["id"]
        assert DailyBriefing.objects.for_team(self.team.id).filter(user_id=self.user.id).count() == 1
        assert sync_connect.return_value.start_workflow.call_count == 1

    def test_the_briefing_day_starts_at_eight(self, sync_connect: MagicMock) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        url = f"/api/projects/{self.team.id}/today/briefing/?timezone=Europe/Prague"
        with self._flag(True):
            # Prague is UTC+2: 07:00 local time still belongs to yesterday's briefing, 09:00 to today's.
            with time_machine.travel(datetime(2026, 9, 30, 5, 0, tzinfo=UTC), tick=False):
                early = self.client.get(url).json()
            with time_machine.travel(datetime(2026, 9, 30, 7, 0, tzinfo=UTC), tick=False):
                today = self.client.get(url).json()
                # A call without a timezone uses the project's UTC, where it is still before eight.
                without_timezone = self.client.get(f"/api/projects/{self.team.id}/today/briefing/").json()

        assert early["local_day"] == "2026-09-29"
        assert today["local_day"] == "2026-09-30"
        assert early["id"] != today["id"]
        assert without_timezone["id"] == early["id"]
        assert sync_connect.return_value.start_workflow.call_count == 2

    def test_a_refresh_while_one_is_being_written_starts_nothing_new(self, sync_connect: MagicMock) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        with self._flag(True):
            responses = [self.client.post(f"/api/projects/{self.team.id}/today/briefing/refresh/") for _ in range(3)]
            DailyBriefing.objects.for_team(self.team.id).filter(user_id=self.user.id).update(
                status=BriefingStatus.READY
            )
            after_ready = self.client.post(f"/api/projects/{self.team.id}/today/briefing/refresh/")

        assert [response.status_code for response in [*responses, after_ready]] == [200, 200, 200, 200]
        # The first refresh starts a run; the next two find it still writing; the last starts a second one.
        assert sync_connect.return_value.start_workflow.call_count == 2

    def test_a_refresh_keeps_the_ready_briefing_on_screen_until_the_new_one_is_written(
        self, sync_connect: MagicMock
    ) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        with self._flag(True):
            first = self.client.get(f"/api/projects/{self.team.id}/today/briefing/").json()
            DailyBriefing.objects.for_team(self.team.id).filter(id=first["id"]).update(
                status=BriefingStatus.READY,
                content={"headline": "Morning text", "paragraphs": [], "labels": {}, "signals": {}},
            )
            refreshed = self.client.post(f"/api/projects/{self.team.id}/today/briefing/refresh/").json()
            while_writing = self.client.get(f"/api/projects/{self.team.id}/today/briefing/").json()
            new_id = (
                DailyBriefing.objects.for_team(self.team.id)
                .filter(user_id=self.user.id, trigger=BriefingTrigger.REFRESH)
                .values_list("id", flat=True)
                .get()
            )
            DailyBriefing.objects.for_team(self.team.id).filter(id=new_id).update(
                status=BriefingStatus.READY,
                content={"headline": "Fresh text", "paragraphs": [], "labels": {}, "signals": {}},
            )
            done = self.client.get(f"/api/projects/{self.team.id}/today/briefing/").json()

        assert (refreshed["id"], refreshed["status"], refreshed["headline"]) == (first["id"], "writing", "Morning text")
        assert (while_writing["status"], while_writing["headline"]) == ("writing", "Morning text")
        assert (done["id"], done["status"], done["headline"]) == (str(new_id), "ready", "Fresh text")

    def test_briefings_of_other_people_stay_private(self, _sync_connect: MagicMock) -> None:
        other = self._create_user("other@example.com")
        with self._flag(True):
            self.client.get(f"/api/projects/{self.team.id}/today/briefing/")
            self.client.force_login(other)
            response = self.client.get(f"/api/projects/{self.team.id}/today/briefing/")

        assert response.status_code == status.HTTP_200_OK
        assert DailyBriefing.objects.for_team(self.team.id).filter(user_id=other.id).count() == 1
        assert DailyBriefing.objects.for_team(self.team.id).count() == 2
