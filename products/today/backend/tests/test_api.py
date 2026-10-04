import json
from dataclasses import replace
from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.llm.system_one import (
    ChoiceAnswer,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
)
from posthog.llm.system_one_client import GatewaySystemOneClient
from posthog.models import PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.facade import api as signals
from products.signals.backend.models import SignalReport
from products.today.backend.facade.enums import BriefingStatus, BriefingTrigger
from products.today.backend.logic import briefings
from products.today.backend.logic.jev import JevPick
from products.today.backend.models import DailyBriefing
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin
from products.today.backend.tests.factories import AGREEING, FakeJev, SameAnswerJev, page_source
from products.today.backend.tests.test_key_clauses import CART_TEXT, CAUSE, CAUSE_EXPLAINED, SUMMARY

REPORT_ID = "01a10212-6f09-0000-0ed6-46b2df6f81ca"
FIGURE_LEAD = "🚨 The export failed for 212 users."
FIGURE_SOURCE = "On Monday 🚨 the export failed for 212 users."
WRITTEN_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


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

    @parameterized.expand(
        [
            ("flag on", True, REPORT_ID, None, status.HTTP_200_OK),
            ("flag off", False, REPORT_ID, None, status.HTTP_404_NOT_FOUND),
            ("not a report id", True, "report-1", None, status.HTTP_404_NOT_FOUND),
            ("no gateway", True, REPORT_ID, SystemOneNotConfigured("no gateway"), status.HTTP_503_SERVICE_UNAVAILABLE),
            (
                "out of ai credits",
                True,
                REPORT_ID,
                SystemOneRequestFailed("payment required", status_code=402),
                status.HTTP_402_PAYMENT_REQUIRED,
            ),
        ]
    )
    def test_key_clauses_answer_only_people_who_may_use_jev(
        self,
        _sync_connect: MagicMock,
        _name: str,
        flag: bool,
        report_id: str,
        gateway_error: Exception | None,
        expected: int,
    ) -> None:
        jev = FakeJev([CART_TEXT], {CAUSE: JevPick(label="cause", probability=0.9)}, {CAUSE: CAUSE_EXPLAINED})
        with (
            self._flag(flag),
            patch("products.today.backend.facade.api.signals.report_summary", return_value=SUMMARY),
            patch("products.today.backend.facade.api.GatewayJev", return_value=jev, side_effect=gateway_error),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/today/reports/{report_id}/key_clauses/",
                {"requests": [{"text": CART_TEXT, "roles": ["problem", "cause"]}]},
                format="json",
            )

        assert response.status_code == expected
        if expected == status.HTTP_200_OK:
            [text] = response.json()["texts"]
            assert [(clause["text"], clause["role"], clause["expansion"]) for clause in text["key_clauses"]] == [
                (CAUSE, "cause", [CAUSE_EXPLAINED])
            ]

    @parameterized.expand(
        [
            ("a signal states the number", True, "signal", None, status.HTTP_200_OK),
            ("the agent's research states the number", True, "research", None, status.HTTP_200_OK),
            ("flag off", False, "signal", None, status.HTTP_404_NOT_FOUND),
            ("no gateway", True, "signal", SystemOneNotConfigured("no gateway"), status.HTTP_503_SERVICE_UNAVAILABLE),
        ]
    )
    def test_figure_marks_name_the_sentence_that_states_each_number(
        self,
        _sync_connect: MagicMock,
        _name: str,
        flag: bool,
        source_kind: str,
        gateway_error: Exception | None,
        expected: int,
    ) -> None:
        signal = signals.ReportSignal(
            signal_id="signal-1",
            content=FIGURE_SOURCE,
            source_product="error_tracking",
            source_type="issue",
            source_id="issue-1",
            timestamp=WRITTEN_AT,
            extra={},
        )
        finding = signals.ReportArtefactText(
            artefact_id="artefact-1",
            type="signal_finding",
            content=json.dumps({"data_queried": FIGURE_SOURCE}),
            created_at=WRITTEN_AT,
            written_by_person=False,
        )
        page = replace(
            page_source(),
            sections=signals.ReportSections(lead=FIGURE_LEAD, impact=None, solution=None),
            signals=[signal] if source_kind == "signal" else [],
        )
        with (
            self._flag(flag),
            patch("products.today.backend.facade.api.signals.report_page_source", return_value=page),
            patch(
                "products.today.backend.facade.api.signals.report_artefact_texts",
                return_value=[finding] if source_kind == "research" else [],
            ),
            patch(
                "products.today.backend.facade.api.GatewayJev",
                return_value=SameAnswerJev(AGREEING),
                side_effect=gateway_error,
            ),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/today/reports/{REPORT_ID}/figure_marks/")

        assert response.status_code == expected
        if expected == status.HTTP_200_OK:
            assert response.json()["marks"] == [
                {
                    "text": "lead",
                    "start": FIGURE_LEAD.index("212") + 1,
                    "end": FIGURE_LEAD.index("212") + 4,
                    "figure": "212",
                    "quote": {
                        "kind": source_kind,
                        "signal_id": "signal-1" if source_kind == "signal" else None,
                        "at": "2026-10-01T09:00:00Z",
                        "sentence": FIGURE_SOURCE,
                        "start": FIGURE_SOURCE.index("212") + 1,
                        "end": FIGURE_SOURCE.index("212") + 4,
                    },
                }
            ]

    @parameterized.expand(
        [
            ("a sure pick", ChoiceAnswer(choice="2", confidence=0.9, probabilities={}), status.HTTP_200_OK, 1),
            ("an unsure pick", ChoiceAnswer(choice="2", confidence=0.3, probabilities={}), status.HTTP_200_OK, None),
            ("a failing gateway", SystemOneRequestFailed("bad gateway", status_code=502), 503, None),
            ("no ai credits", SystemOneRequestFailed("payment required", status_code=402), 402, None),
        ]
    )
    def test_excerpt_choice_asks_the_gateway_once_for_the_finding(
        self,
        _sync_connect: MagicMock,
        _name: str,
        outcome: ChoiceAnswer | Exception,
        expected: int,
        index: int | None,
    ) -> None:
        cache.clear()
        client = GatewaySystemOneClient(
            url="https://gateway.example.com", api_key="test-key", headers={}, model="jev", timeout=30
        )

        def adecide(state: dict[str, str], questions: dict[str, Question]) -> SystemOneResult:
            if isinstance(outcome, Exception):
                raise outcome
            return SystemOneResult(model="jev", answers=dict.fromkeys(questions, outcome), input_tokens=1)

        with (
            self._flag(True),
            patch("products.today.backend.logic.jev.build_system_one_client", return_value=client),
            patch.object(GatewaySystemOneClient, "adecide", AsyncMock(side_effect=adecide)) as decide,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/today/excerpt_choice/",
                {"finding": "The cart drops the token.", "excerpts": ["a = 1", "drop(token)"]},
                format="json",
            )

        assert response.status_code == expected
        assert decide.await_count == 1
        if expected == status.HTTP_200_OK:
            assert response.json() == {"index": index}

    @parameterized.expand(
        [
            ("a report", True, REPORT_ID, status.HTTP_200_OK, "Lead."),
            ("flag off", False, REPORT_ID, status.HTTP_404_NOT_FOUND, None),
            ("a sample report", True, "sample-pr", status.HTTP_200_OK, "Safari users can’t finish checkout"),
            ("an unknown sample", True, "sample-nope", status.HTTP_404_NOT_FOUND, None),
        ]
    )
    def test_report_page_answers_people_with_the_new_navigation(
        self, _sync_connect: MagicMock, _name: str, flag: bool, report_id: str, expected: int, lead: str | None
    ) -> None:
        with (
            self._flag(flag),
            patch("products.today.backend.logic.report_page.signals.report_page_source", return_value=page_source()),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/today/reports/{report_id}/page/")

        assert response.status_code == expected
        if lead is not None:
            assert response.json()["lead"].startswith(lead)

    @parameterized.expand(
        [
            ("the page with only today", "get", "page", ["today:read"], status.HTTP_403_FORBIDDEN),
            ("the page with today and signals", "get", "page", ["today:read", "task:read"], status.HTTP_200_OK),
            ("key clauses with only today", "post", "key_clauses", ["today:read"], status.HTTP_403_FORBIDDEN),
            ("figure marks with only today", "get", "figure_marks", ["today:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_a_scoped_key_reads_report_data_only_with_the_signals_scope(
        self, _sync_connect: MagicMock, _name: str, method: str, endpoint: str, scopes: list[str], expected: int
    ) -> None:
        raw_key = "today_report_page_key"
        PersonalAPIKey.objects.create(
            user=self.user, label="Today", secure_value=hash_key_value(raw_key), scopes=scopes
        )
        self.client.logout()
        with (
            self._flag(True),
            patch("products.today.backend.logic.report_page.signals.report_page_source", return_value=page_source()),
        ):
            response = getattr(self.client, method)(
                f"/api/projects/{self.team.id}/today/reports/{REPORT_ID}/{endpoint}/",
                HTTP_AUTHORIZATION=f"Bearer {raw_key}",
            )

        assert response.status_code == expected

    @parameterized.expand(
        [
            ("the page, with access", "page", None, status.HTTP_200_OK),
            ("the page, without access", "page", "none", status.HTTP_403_FORBIDDEN),
            ("key clauses, without access", "key_clauses", "none", status.HTTP_403_FORBIDDEN),
            ("figure marks, without access", "figure_marks", "none", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_a_member_reads_report_data_only_with_access_to_inbox_reports(
        self, _sync_connect: MagicMock, _name: str, endpoint: str, task_access: str | None, expected: int
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        if task_access is not None:
            AccessControl.objects.create(team=self.team, resource="task", resource_id=None, access_level=task_access)
        self.client.force_login(User.objects.create_and_join(self.organization, "member@example.com", "testtest"))
        url = f"/api/projects/{self.team.id}/today/reports/{REPORT_ID}/{endpoint}/"
        with (
            self._flag(True),
            patch("products.today.backend.logic.report_page.signals.report_page_source", return_value=page_source()),
        ):
            if endpoint == "key_clauses":
                response = self.client.post(
                    url, {"requests": [{"text": CART_TEXT, "roles": ["problem"]}]}, format="json"
                )
            else:
                response = self.client.get(url)

        assert response.status_code == expected

    @parameterized.expand([("a deleted report", True, False), ("another team's report", False, True)])
    def test_report_page_answers_404_for(
        self, _sync_connect: MagicMock, _name: str, deleted: bool, other: bool
    ) -> None:
        team = Team.objects.create(organization=self.organization) if other else self.team
        report = SignalReport.objects.create(
            team=team,
            title="Checkout fails",
            summary="Checkout fails for some shoppers.",
            status=SignalReport.Status.DELETED if deleted else SignalReport.Status.READY,
            signal_count=1,
            total_weight=1.0,
        )
        with (
            self._flag(True),
            patch("products.signals.backend.report_page_source.fetch_signals_for_report_sync", return_value=[]),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/today/reports/{report.id}/page/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
