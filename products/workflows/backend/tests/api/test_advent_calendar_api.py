import threading
from datetime import UTC, datetime
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.conf import settings
from django.core.cache import caches
from django.db import connections, transaction
from django.db.models.signals import pre_delete
from django.test import TransactionTestCase, override_settings

from django_redis.cache import RedisCache
from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team, User
from posthog.models.instance_setting import override_instance_config
from posthog.rate_limit import is_rate_limit_enabled
from posthog.test.lagging_redis_reader import lagging_reader_caches, unique_key_prefix
from posthog.test.waiting import wait_until

from products.workflows.backend.facade.advent_calendar import answer_advent_calendar, open_advent_calendar_door
from products.workflows.backend.facade.enums import AdventCalendarDay, AdventCalendarOption
from products.workflows.backend.models import AdventCalendarAnswer, AdventCalendarDoorOpen


class TestAdventCalendarAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.outsider = User.objects.create_and_join(self.organization, "outsider@example.com", "password")
        flag_patch = patch(
            "posthog.permissions.posthog_feature_flag_enabled",
            side_effect=lambda flag, distinct_id, **kwargs: (
                flag == "workflows-advent-calendar" and distinct_id != str(self.outsider.distinct_id)
            ),
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def _url(self, team: Team, action: str) -> str:
        return f"/api/projects/{team.id}/workflow_advent_calendar/{action}/"

    def _answer_as(self, user: User, team: Team, day: int, option: str) -> Any:
        self.client.force_login(user)
        response = self.client.post(self._url(team, "answer"), {"day": day, "option": option})
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _open_door_as(self, user: User, day: int, hoggy: str, utc_offset_minutes: int) -> Any:
        self.client.force_login(user)
        response = self.client.post(
            self._url(self.team, "open"), {"day": day, "hoggy": hoggy, "utc_offset_minutes": utc_offset_minutes}
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _results(self) -> list[dict[str, Any]]:
        self.client.force_login(self.user)
        response = self.client.get(self._url(self.team, "results"))
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["questions"]

    def _member_of_another_organization(self, email: str) -> tuple[User, Team]:
        organization = Organization.objects.create(name="Other organization")
        team = Team.objects.create(organization=organization, name="Other project")
        user = User.objects.create_and_join(organization, email, "password")
        return user, team

    def test_results_count_answers_from_every_project_and_show_only_the_callers_own_answers(self) -> None:
        james_fan, other_team = self._member_of_another_organization("james-fan@example.com")
        self._answer_as(james_fan, other_team, 2, "james")
        self._answer_as(james_fan, other_team, 5, "yes")
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        self._answer_as(teammate, self.team, 2, "tim")
        self._answer_as(self.user, self.team, 2, "tim")

        questions = self._results()

        assert [question["day"] for question in questions] == [2, 5, 10, 13, 18, 21]
        results = {question["day"]: question for question in questions}
        assert results[2] == {
            "day": 2,
            "answer": "tim",
            "shares": [{"option": "james", "share": 33}, {"option": "tim", "share": 67}],
        }
        assert results[5] == {
            "day": 5,
            "answer": None,
            "shares": [{"option": "yes", "share": 100}, {"option": "no", "share": 0}],
        }
        assert results[21] == {
            "day": 21,
            "answer": None,
            "shares": [{"option": "coffee", "share": 0}, {"option": "tea", "share": 0}],
        }

    def test_answers_and_door_opens_of_deleted_accounts_are_removed(self) -> None:
        leaver = User.objects.create_and_join(self.organization, "leaver@example.com", "password")
        self._answer_as(leaver, self.team, 18, "no")
        self._open_door_as(leaver, 18, "hoggy-santa", 60)
        self._answer_as(self.user, self.team, 18, "yes")
        self._open_door_as(self.user, 18, "hoggy-elf", 0)
        leaver.organization_memberships.all().delete()
        self.client.force_login(leaver)

        def vote_lands_during_the_deletion(sender: type, instance: User, **kwargs: Any) -> None:
            AdventCalendarAnswer.objects.create(user_id=instance.id, day=21, option="tea")

        pre_delete.connect(vote_lands_during_the_deletion, sender=User, dispatch_uid="advent_test_vote_during_deletion")
        self.addCleanup(pre_delete.disconnect, sender=User, dispatch_uid="advent_test_vote_during_deletion")

        deletion = self.client.delete("/api/users/@me/")

        assert deletion.status_code == status.HTTP_204_NO_CONTENT
        assert not AdventCalendarAnswer.objects.filter(user_id=leaver.id).exists()
        assert not AdventCalendarDoorOpen.objects.filter(user_id=leaver.id).exists()
        assert list(AdventCalendarDoorOpen.objects.values_list("user_id", "day", "hoggy")) == [
            (self.user.id, 18, "hoggy-elf")
        ]
        day_18 = next(question for question in self._results() if question["day"] == 18)
        assert day_18["shares"] == [{"option": "yes", "share": 100}, {"option": "no", "share": 0}]

    def test_the_first_answer_for_a_day_stands(self) -> None:
        self._answer_as(self.user, self.team, 13, "dark")

        second = self._answer_as(self.user, self.team, 13, "light")

        day_13 = next(question for question in second["questions"] if question["day"] == 13)
        assert day_13 == {
            "day": 13,
            "answer": "dark",
            "shares": [{"option": "dark", "share": 100}, {"option": "light", "share": 0}],
        }

    def test_the_first_open_of_a_door_stores_the_server_time_and_a_repeat_keeps_it(self) -> None:
        with time_machine.travel(datetime(2026, 12, 3, 7, 30, tzinfo=UTC), tick=False) as traveller:
            first = self._open_door_as(self.user, 3, "hoggy-santa", -300)
            traveller.shift(86400)
            repeat = self._open_door_as(self.user, 3, "hoggy-elf", 60)
            other_day = self._open_door_as(self.user, 4, "hoggy-elf", 60)

        assert first == {"day": 3, "opened_at": "2026-12-03T07:30:00Z"}
        assert repeat == first
        assert other_day == {"day": 4, "opened_at": "2026-12-04T07:30:00Z"}
        stored = AdventCalendarDoorOpen.objects.get(user_id=self.user.id, day=3)
        assert (stored.hoggy, stored.utc_offset_minutes) == ("hoggy-santa", -300)

    def test_an_open_from_an_account_deleted_after_sign_in_returns_not_found(self) -> None:
        with patch(
            "products.workflows.backend.presentation.views.workflow_advent_calendar.open_advent_calendar_door",
            return_value=None,
        ):
            response = self.client.post(
                self._url(self.team, "open"), {"day": 2, "hoggy": "hoggy-santa", "utc_offset_minutes": 0}
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

    @parameterized.expand(
        [
            ("day_before_the_first", {"day": 0, "hoggy": "hoggy-santa", "utc_offset_minutes": 0}),
            ("day_after_the_last", {"day": 25, "hoggy": "hoggy-santa", "utc_offset_minutes": 0}),
            ("uppercase_hoggy", {"day": 1, "hoggy": "Hoggy", "utc_offset_minutes": 0}),
            ("hoggy_with_a_path", {"day": 1, "hoggy": "../hoggy", "utc_offset_minutes": 0}),
            ("hoggy_too_long", {"day": 1, "hoggy": "h" * 65, "utc_offset_minutes": 0}),
            ("offset_west_of_utc_minus_12", {"day": 1, "hoggy": "hoggy-santa", "utc_offset_minutes": -721}),
            ("offset_east_of_utc_plus_14", {"day": 1, "hoggy": "hoggy-santa", "utc_offset_minutes": 841}),
            ("missing_offset", {"day": 1, "hoggy": "hoggy-santa"}),
            ("hoggy_sent_as_a_number", {"day": 1, "hoggy": 123, "utc_offset_minutes": 0}),
            ("hoggy_padded_with_spaces", {"day": 1, "hoggy": " hoggy-santa", "utc_offset_minutes": 0}),
            ("hoggy_ending_in_a_newline", {"day": 1, "hoggy": "hoggy-santa\n", "utc_offset_minutes": 0}),
        ]
    )
    def test_open_rejects_a_door_hoggy_or_offset_out_of_range(self, _name: str, body: dict[str, Any]) -> None:
        response = self.client.post(self._url(self.team, "open"), body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert not AdventCalendarDoorOpen.objects.exists()

    @parameterized.expand(
        [
            ("day_without_a_question", {"day": 3, "option": "yes"}),
            ("option_of_another_day", {"day": 2, "option": "yes"}),
            ("free_text_option", {"day": 10, "option": "both"}),
            ("missing_option", {"day": 10}),
        ]
    )
    def test_answer_rejects_anything_outside_the_six_questions(self, _name: str, body: dict[str, Any]) -> None:
        response = self.client.post(self._url(self.team, "answer"), body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert not AdventCalendarAnswer.objects.exists()

    def test_people_outside_the_advent_calendar_rollout_can_neither_answer_open_nor_read(self) -> None:
        self.client.force_login(self.outsider)

        answer = self.client.post(self._url(self.team, "answer"), {"day": 2, "option": "tim"})
        results = self.client.get(self._url(self.team, "results"))
        door = self.client.post(
            self._url(self.team, "open"), {"day": 2, "hoggy": "hoggy-santa", "utc_offset_minutes": 0}
        )

        assert answer.status_code == status.HTTP_403_FORBIDDEN
        assert results.status_code == status.HTTP_403_FORBIDDEN
        assert door.status_code == status.HTTP_403_FORBIDDEN
        assert not AdventCalendarAnswer.objects.exists()
        assert not AdventCalendarDoorOpen.objects.exists()
        self._results()

    def test_each_signed_in_person_has_their_own_request_budget_even_with_api_rate_limits_off(self) -> None:
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        with (
            override_settings(
                CACHES={**settings.CACHES, **lagging_reader_caches(unique_key_prefix("test-advent-calendar-throttle"))}
            ),
            override_instance_config("RATE_LIMIT_ENABLED", False),
        ):
            try:
                is_rate_limit_enabled.cache_clear()
                self._answer_as(self.user, self.team, 2, "tim")
                self._open_door_as(self.user, 2, "hoggy-santa", 0)
                for _ in range(28):
                    self._results()
                over_budget = self.client.get(self._url(self.team, "results"))
                teammate_answer = self._answer_as(teammate, self.team, 2, "james")
            finally:
                for alias in ("default", "throttle_history"):
                    redis_cache = caches[alias]
                    assert isinstance(redis_cache, RedisCache)
                    redis_cache.delete_pattern("*")
                is_rate_limit_enabled.cache_clear()

        assert over_budget.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert teammate_answer["questions"][0]["shares"] == [
            {"option": "james", "share": 50},
            {"option": "tim", "share": 50},
        ]


class TestAdventCalendarAnswers(BaseTest):
    def test_an_answer_for_an_account_deleted_meanwhile_stores_nothing(self) -> None:
        answer_advent_calendar(self.user.id + 1000, AdventCalendarDay.COFFEE_OR_TEA, AdventCalendarOption.TEA)

        assert not AdventCalendarAnswer.objects.exists()

    def test_a_door_opened_by_an_account_deleted_meanwhile_stores_nothing(self) -> None:
        assert open_advent_calendar_door(self.user.id + 1000, 7, "hoggy-santa", 0) is None
        assert not AdventCalendarDoorOpen.objects.exists()


class TestAdventCalendarDoorOpenRace(TransactionTestCase):
    def test_a_door_opened_while_its_account_is_being_deleted_is_not_left_behind(self) -> None:
        racer = User.objects.create_user(email="racer@example.com", password=None, first_name="Racer")
        racer_id = racer.id
        opened = threading.Event()
        opener_pids: list[int] = []
        results: list[Any] = []

        def open_door() -> None:
            try:
                connections["default"].ensure_connection()
                opener_pids.append(connections["default"].connection.info.backend_pid)
                results.append(
                    open_advent_calendar_door(user_id=racer_id, day=5, hoggy="hoggy-santa", utc_offset_minutes=0)
                )
            finally:
                opened.set()
                connections.close_all()

        def opener_waits_on_the_deletion() -> bool:
            if not opener_pids:
                return False
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))",
                    [opener_pids[0]],
                )
                row = cursor.fetchone()
            return row is not None and bool(row[0])

        opener = threading.Thread(target=open_door)
        try:
            with transaction.atomic():
                racer.delete()
                opener.start()
                wait_until(lambda: opened.is_set() or opener_waits_on_the_deletion())
        finally:
            if opener.ident is not None:
                opener.join(timeout=10)
        assert not opener.is_alive()

        assert results == [None]
        assert not AdventCalendarDoorOpen.objects.exists()
