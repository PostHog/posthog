import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

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
from products.today.backend.logic import highlights, pinned
from products.today.backend.logic.highlight_types import Found, Source
from products.today.backend.logic.jev import JevPick
from products.today.backend.temporal.inputs import (
    ComputeHighlightsInputs,
    FinalizeHighlightsInputs,
    HighlightSourceInputs,
    ResolvePinsInputs,
)
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin
from products.today.backend.tests.factories import AGREEING, FakeJev, SameAnswerJev, page_source
from products.today.backend.tests.test_highlights import candidate, metric
from products.today.backend.tests.test_key_clauses import CART_TEXT, CAUSE, CAUSE_EXPLAINED, SUMMARY

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

REPORT_ID = "01a10212-6f09-0000-0ed6-46b2df6f81ca"
FIGURE_LEAD = "🚨 The export failed for 212 users."
FIGURE_SOURCE = "On Monday 🚨 the export failed for 212 users."
WRITTEN_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


class TestTodayAPI(TodayTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _flag(self, enabled: bool | frozenset[str]):
        if isinstance(enabled, bool):
            return patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=enabled)
        return patch(
            "products.today.backend.feature_flags.feature_enabled_or_false",
            side_effect=lambda flag, *args, **kwargs: flag in enabled,
        )

    @parameterized.expand(
        [
            ("flag on", True, REPORT_ID, None, status.HTTP_200_OK),
            ("flag off", False, REPORT_ID, None, status.HTTP_404_NOT_FOUND),
            (
                "the jev flag without the new navigation",
                frozenset({"today-report-jev"}),
                REPORT_ID,
                None,
                status.HTTP_404_NOT_FOUND,
            ),
            ("not a report id", True, "report-1", None, status.HTTP_404_NOT_FOUND),
            ("no gateway", True, REPORT_ID, SystemOneNotConfigured("no gateway"), status.HTTP_503_SERVICE_UNAVAILABLE),
            (
                "the gateway refuses to bill",
                True,
                REPORT_ID,
                SystemOneRequestFailed("payment required", status_code=402),
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
        ]
    )
    def test_key_clauses_answer_only_people_who_may_use_jev(
        self,
        _name: str,
        flag: bool | frozenset[str],
        report_id: str,
        gateway_error: Exception | None,
        expected: int,
    ) -> None:
        jev = FakeJev([CART_TEXT], {CAUSE: JevPick(label="cause", probability=0.9)}, {CAUSE: CAUSE_EXPLAINED})
        page = replace(
            page_source(summary=SUMMARY),
            sections=signals.ReportSections(lead=CART_TEXT, impact=None, solution=None),
        )
        with (
            self._flag(flag),
            patch("products.today.backend.facade.api.signals.report_page_source", return_value=page),
            patch("products.today.backend.facade.api.GatewayJev", return_value=jev, side_effect=gateway_error),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/today/reports/{report_id}/key_clauses/")

        assert response.status_code == expected
        if expected == status.HTTP_200_OK:
            found = response.json()
            assert (found["impact"], found["proposal"]) == ([], [])
            assert [
                (CART_TEXT[clause["start"] : clause["end"]], clause["role"], clause["expansion"])
                for clause in found["lead"]
            ] == [(CAUSE, "cause", [CAUSE_EXPLAINED])]

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
                "products.today.backend.facade.api.signals.report_agent_texts",
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
            marks = response.json()["marks"]
            quote_signal = marks[0]["quote"].pop("signal")
            assert (quote_signal or {}).get("signal_id") == ("signal-1" if source_kind == "signal" else None)
            assert marks == [
                {
                    "text": "lead",
                    "start": FIGURE_LEAD.index("212") + 1,
                    "end": FIGURE_LEAD.index("212") + 4,
                    "figure": "212",
                    "quote": {
                        "kind": source_kind,
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
            ("a gateway that refuses to bill", SystemOneRequestFailed("payment required", status_code=402), 503, None),
        ]
    )
    def test_excerpt_choice_asks_the_gateway_once_for_the_finding(
        self,
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
        self, _name: str, flag: bool, report_id: str, expected: int, lead: str | None
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
            ("the page with only today", "get", f"reports/{REPORT_ID}/page", ["today:read"], status.HTTP_403_FORBIDDEN),
            (
                "the page with today and signals",
                "get",
                f"reports/{REPORT_ID}/page",
                ["today:read", "task:read"],
                status.HTTP_200_OK,
            ),
            (
                "key clauses with only today",
                "get",
                f"reports/{REPORT_ID}/key_clauses",
                ["today:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "figure marks with only today",
                "get",
                f"reports/{REPORT_ID}/figure_marks",
                ["today:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            ("highlights with only today", "get", "highlights", ["today:read"], status.HTTP_403_FORBIDDEN),
            ("pins with today read", "get", "pulse_pins", ["today:read"], status.HTTP_200_OK),
            ("saving pins with today read", "put", "pulse_pins", ["today:read"], status.HTTP_403_FORBIDDEN),
            ("saving pins with today write", "put", "pulse_pins", ["today:write"], status.HTTP_200_OK),
        ]
    )
    def test_a_scoped_key_reads_data_only_with_its_underlying_scope(
        self, _name: str, method: str, path: str, scopes: list[str], expected: int
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
                f"/api/projects/{self.team.id}/today/{path}/",
                {"pins": []} if method == "put" else None,
                format="json",
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
        self, _name: str, endpoint: str, task_access: str | None, expected: int
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
            response = self.client.get(url)

        assert response.status_code == expected

    @parameterized.expand([("a deleted report", True, False), ("another team's report", False, True)])
    def test_report_page_answers_404_for(self, _name: str, deleted: bool, other: bool) -> None:
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


def _temporal() -> MagicMock:
    connect = MagicMock()
    connect.return_value.start_workflow = AsyncMock()
    return connect


class TestTodayHighlightsAPI(TodayTeamScopedTestMixin, APIBaseTest):
    def _get(self, connect: MagicMock, flag: bool = True, pulse: tuple[str, ...] = ("k1",)) -> "_MonkeyPatchedResponse":
        source = Source(
            name="alerts",
            find=lambda _c: Found(
                items=(candidate("alert:1", "alerts", 0.8),), pulse=tuple(metric(key) for key in pulse)
            ),
        )
        with (
            patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=flag),
            patch.object(highlights, "load_sources", return_value=(source,)),
            patch.object(highlights, "sync_connect", connect),
            patch.object(pinned, "get_key_metrics", return_value=[]),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/today/highlights/")
            if response.status_code == status.HTTP_200_OK and connect.return_value.start_workflow.called:
                inputs: ComputeHighlightsInputs = connect.return_value.start_workflow.call_args.args[1]
                results = [
                    highlights.run_source(
                        HighlightSourceInputs(
                            team_id=inputs.team_id,
                            user_id=inputs.user_id,
                            local_day=inputs.local_day,
                            scopes=inputs.scopes,
                            source_name=name,
                        )
                    )
                    for name in inputs.source_names
                ]
                found_pins = (
                    pinned.resolve_pins(
                        ResolvePinsInputs(
                            team_id=inputs.team_id,
                            user_id=inputs.user_id,
                            local_day=inputs.local_day,
                            scopes=inputs.scopes,
                            pins=inputs.pins,
                        )
                    ).found
                    if inputs.pins
                    else "[]"
                )
                highlights.finalize(
                    FinalizeHighlightsInputs(
                        team_id=inputs.team_id,
                        highlights_id=inputs.highlights_id,
                        results=results,
                        pins=inputs.pins,
                        pinned=found_pins,
                    )
                )
        return response

    @parameterized.expand([("flag on", True, status.HTTP_200_OK), ("flag off", False, status.HTTP_404_NOT_FOUND)])
    def test_highlights_need_the_flag_but_not_ai(self, _name: str, flag: bool, expected: int) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        cache.clear()

        response = self._get(_temporal(), flag)

        self.assertEqual(response.status_code, expected)

    @time_machine.travel(datetime(2026, 10, 13, 12, 0, tzinfo=UTC), tick=False)
    def test_the_first_call_starts_the_computation_and_a_later_call_serves_its_result(self) -> None:
        cache.clear()
        connect = _temporal()

        first = self._get(_temporal()).json()
        second = self._get(connect).json()

        self.assertEqual(
            (
                (first["status"], first["generated_at"], first["pulse"], first["items"]),
                second["status"],
                [(m["key"], m["interval"], m["value_format"], len(m["period_starts"])) for m in second["pulse"]],
                [(i["key"], i["source"], i["label"], i["priority"], i["series"]) for i in second["items"]],
                connect.return_value.start_workflow.called,
            ),
            (
                ("computing", None, [], []),
                "ready",
                [("k1", "day", None, 1)],
                [("alert:1", "alerts", "risk", "P1", None)],
                False,
            ),
        )

    def test_pinned_numbers_lead_the_pulse_and_a_new_pin_starts_a_new_computation(self) -> None:
        cache.clear()
        with time_machine.travel(datetime(2026, 10, 13, 12, 0, tzinfo=UTC), tick=False) as clock:
            self._get(_temporal(), pulse=("k1", "k2"))
            pins = [{"key": key, "name": key} for key in ("k2", "k2", "a", "b", "c", "d")]
            clock.shift(timedelta(seconds=1))
            with patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=True):
                saved = self.client.put(
                    f"/api/projects/{self.team.id}/today/pulse_pins/", {"pins": pins}, format="json"
                )
                read = self.client.get(f"/api/projects/{self.team.id}/today/pulse_pins/")
            connect = _temporal()
            during = self._get(connect, pulse=("k1", "k2")).json()
            after = self._get(_temporal(), pulse=("k1", "k2")).json()
            with patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=True):
                self.client.put(f"/api/projects/{self.team.id}/today/pulse_pins/", {"pins": []}, format="json")
            back = _temporal()
            self._get(back, pulse=("k1", "k2"))

        self.assertEqual(
            (
                [pin["key"] for pin in saved.json()["pins"]],
                read.json() == saved.json(),
                (connect.return_value.start_workflow.called, back.return_value.start_workflow.called),
                (during["status"], [m["key"] for m in during["pulse"]]),
                [m["key"] for m in after["pulse"]],
                [(pin["key"], pin["status"]) for pin in after["pins"]],
            ),
            (
                ["k2", "a", "b", "c"],
                True,
                (True, True),
                ("computing", ["k1", "k2"]),
                ["k2", "k1"],
                [("k2", "ready"), ("a", "unavailable"), ("b", "unavailable"), ("c", "unavailable")],
            ),
        )

    def test_saving_too_many_pins_is_rejected(self) -> None:
        pins = [{"key": f"k{index}", "name": f"k{index}"} for index in range(21)]

        with patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=True):
            response = self.client.put(f"/api/projects/{self.team.id}/today/pulse_pins/", {"pins": pins}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
