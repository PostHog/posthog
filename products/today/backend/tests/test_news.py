import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import User

from products.today.backend.facade.contracts import NewsBrief, NewsStory
from products.today.backend.facade.enums import NewsTone
from products.today.backend.logic.news import candidates, editions, plan, writer
from products.today.backend.logic.news.assemble import StoredBrief, StoredEdition, StoredLead, StoredStory, lead_story
from products.today.backend.logic.news.candidates import Candidate
from products.today.backend.models import TodayHighlights, TodayNewsEdition
from products.today.backend.temporal.inputs import GenerateNewsInputs
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def candidate(index: int, source: str, today: float, change: str) -> Candidate:
    return Candidate(
        id=f"c{index}",
        source=source,
        key=f"k{index}",
        name=f"n{index}",
        today=today,
        baseline=0,
        change=change,
        unit="people",
        context={},
    )


def fact(ref: str, kind: str, severity: str, people: float, change: str = "+30%", surface: str = "app") -> plan.Fact:
    return plan.Fact(
        ref=ref,
        candidates=(candidate(int(ref[1:]), "error" if kind == "error" else "key metric", people, change),),
        kind=kind,
        severity=severity,
        surface=surface,
        what="",
        trend="",
        look_next="",
    )


def copy(
    title: str = "About 400 people can't open dashboards", summary: str = "None did last week. Check the release."
) -> dict[str, str]:
    return {"title": title, "summary": summary, "dive_prompt": "What broke dashboards?"}


def story(story_id: str, scopes: tuple[str, ...]) -> StoredStory:
    return StoredStory(
        story=NewsStory(
            id=story_id,
            product="",
            product_label="",
            title=story_id,
            summary="",
            change=None,
            tone=NewsTone.RISK,
            dive_prompt="",
        ),
        scopes=scopes,
    )


class TestNewsRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("absent for 4 weeks", 150, 0, "new"),
            ("a clear rise", 130, 100, "+30%"),
            ("a small rise", 110, 100, None),
            ("a clear drop", 60, 100, "-40%"),
            ("new but too few people", 50, 0, None),
        ]
    )
    def test_only_clear_changes_become_candidates(
        self, _name: str, today: float, baseline: float, expected: str | None
    ) -> None:
        assert candidates.describe_change(today, baseline) == expected

    def test_screen_tracking_and_new_tracking_are_not_news(self) -> None:
        rows = [
            ("insight timeout message shown", 260, 200, 200, 200, 200),
            ("nav panel card shown", 9000, 4000, 4000, 4000, 4000),
            ("wizard manual setup", 360, 0, 0, 0, 0),
            ("user signed up", 1400, 1000, 1000, 1000, 1000),
        ]

        assert [c.name for c in candidates.from_actions(rows)] == ["insight timeout message shown", "user signed up"]

    @parameterized.expand(
        [
            (
                "a lockout leads over a bigger error",
                [fact("f1", "error", "broken", 900, "new"), fact("f2", "error", "blocked", 40, "new", "app sign-in")],
                "f2",
                [["f1"]],
                [],
            ),
            (
                "a mild rise cannot lead, growth does, and website errors stay in the briefs",
                [
                    fact("f1", "error", "broken", 900, "+26%"),
                    fact("f2", "growth", "signal", 4000),
                    fact("f3", "error", "broken", 700, "new", "website"),
                ],
                "f2",
                [["f1"]],
                ["f3"],
            ),
            (
                "app errors are grouped into one story",
                [
                    fact("f1", "error", "broken", 400, "new"),
                    fact("f2", "error", "broken", 300, "new"),
                    fact("f3", "error", "broken", 200, "new"),
                ],
                "f1",
                [["f2", "f3"]],
                [],
            ),
        ]
    )
    def test_the_plan_picks_the_lead_stories_and_briefs(
        self, _name: str, facts: list[plan.Fact], lead: str, stories: list[list[str]], briefs: list[str]
    ) -> None:
        built = plan.build(facts)

        assert built is not None
        assert built.lead[0].ref == lead
        assert [[f.ref for f in slot] for slot in built.stories] == stories
        assert [f.ref for f in built.briefs] == briefs

    def test_a_draft_must_fill_every_slot_and_follow_the_rules(self) -> None:
        long_summary = " ".join(["word"] * 30) + "; more"

        assert writer.parse_draft({"lead": copy(), "stories": [], "briefs": []}, 1, 0) is None
        draft = writer.parse_draft(
            {"lead": copy(summary=long_summary), "stories": [], "briefs": [{"label": "couldn't open recordings"}]}, 0, 1
        )
        assert draft is not None
        assert writer.rule_breaks(draft) == ["the lead summary has 31 words, max 25", "it uses a semicolon"]

    def test_a_viewer_only_sees_stories_and_briefs_they_may_read(self) -> None:
        errors = story("error:a", ("error_tracking:read",))
        stored = StoredEdition(
            lead=StoredLead(story=lead_story(errors.story), scopes=errors.scopes),
            stories=(story("error:b", ("error_tracking:read",)), story("key metric:c", ("query:read",))),
            briefs=(
                StoredBrief(
                    brief=NewsBrief(
                        id="error:d",
                        value=200,
                        text="hit an error",
                        change=None,
                        is_new=True,
                        tone=NewsTone.RISK,
                        series=[],
                        series_labels=[],
                    ),
                    scopes=("error_tracking:read",),
                ),
            ),
        )

        shown = editions.visible_edition(
            stored, lambda scopes: "error_tracking:read" not in scopes, "edition-1", date(2026, 11, 4)
        )

        assert shown is not None
        assert (shown.lead.id, shown.stories, shown.briefs) == ("key metric:c", [], [])


def llm_replies(*replies: dict[str, Any]) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))],
            model="gpt-6-luna",
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )
        for reply in replies
    ]
    build = MagicMock()
    build.return_value.with_options.return_value = client
    return build


def clickhouse(rows: dict[str, list[tuple[Any, ...]]]) -> Any:
    def run(_team: Any, _statement: str, _anchor: datetime, name: str, **values: Any) -> list[tuple[Any, ...]]:
        if name == "series":
            return [(key, days_ago, 10.0) for key in values["keys"] for days_ago in range(14)]
        return rows.get(name, [])

    return run


@time_machine.travel(NOW, tick=False)
class TestNewsAPI(TodayTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        for user in (self.user, self.teammate):
            TodayHighlights.objects.for_team(self.team.id).create(
                team_id=self.team.id, user_id=user.id, local_day=NOW.date(), key="k"
            )

    def _get(self, connect: MagicMock) -> dict[str, Any]:
        with (
            patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=True),
            patch.object(editions, "sync_connect", connect),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/today/news/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _start(self) -> tuple[MagicMock, GenerateNewsInputs]:
        connect = MagicMock()
        connect.return_value.start_workflow = AsyncMock()
        assert self._get(connect) == {"status": "computing", "skip_reason": None, "edition": None}
        assert self._get(connect)["status"] == "computing"
        assert connect.return_value.start_workflow.await_count == 1
        return connect, connect.return_value.start_workflow.call_args.args[1]

    def test_the_first_request_starts_one_edition_and_a_later_one_serves_it(self) -> None:
        connect, inputs = self._start()
        rows: dict[str, list[tuple[Any, ...]]] = {
            "errors": [
                ("issue-a", "Error", "Can not find path", "/project/1/dashboard", "app.example.com", 400, 0, 0, 0, 0)
            ],
            "key_events": [("user signed up", 1400, 1000, 1000, 1000, 1000)],
        }
        analyst = {
            "facts": [
                {
                    "ids": ["c1"],
                    "kind": "error",
                    "severity": "broken",
                    "surface": "app",
                    "what": "Dashboards fail",
                    "trend": "new",
                    "look_next": "the release",
                },
                {
                    "ids": ["c2"],
                    "kind": "growth",
                    "severity": "signal",
                    "surface": "onboarding",
                    "what": "Sign-ups rose",
                    "trend": "+40%",
                    "look_next": "sources",
                },
            ]
        }
        editor = {
            "lead": copy(),
            "stories": [copy("Sign-ups rose 40%", "More people joined. Check the sources.")],
            "briefs": [],
        }

        with patch.object(editions.queries, "run", clickhouse(rows)):
            assert editions.collect_facts(inputs) is True
            with (
                patch.object(writer, "build_openai_client", llm_replies(analyst, editor)),
                patch.object(editions.posthoganalytics, "capture") as capture,
            ):
                editions.write_edition(inputs)
        body = self._get(connect)

        assert body["status"] == "ready"
        lead, stories = body["edition"]["lead"], body["edition"]["stories"]
        assert (lead["id"], lead["title"], lead["metric_value"], len(lead["series"])) == (
            "error:issue-a",
            copy()["title"],
            "10",
            14,
        )
        assert [(item["id"], item["change"], item["tone"]) for item in stories] == [
            ("key metric:user signed up", 40.0, "good")
        ]
        assert capture.call_args.kwargs["event"] == editions.GENERATED_EVENT
        assert capture.call_args.kwargs["properties"]["outcome"] == "ready"
        assert connect.return_value.start_workflow.await_count == 1

    def test_a_quiet_day_is_skipped_without_a_model_call(self) -> None:
        connect, inputs = self._start()
        build = llm_replies()

        with patch.object(editions.queries, "run", clickhouse({})), patch.object(writer, "build_openai_client", build):
            proceed = editions.collect_facts(inputs)

        assert proceed is False
        build.assert_not_called()
        assert self._get(connect) == {"status": "skipped", "skip_reason": "quiet", "edition": None}

    @parameterized.expand([("ai not approved", "ai_not_approved"), ("one person uses today", "few_people")])
    def test_a_failed_gate_starts_nothing(self, _name: str, reason: str) -> None:
        if reason == "ai_not_approved":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save()
        else:
            TodayHighlights.objects.for_team(self.team.id).filter(user_id=self.teammate.id).delete()
        connect = MagicMock()

        assert self._get(connect) == {"status": "skipped", "skip_reason": reason, "edition": None}
        connect.return_value.start_workflow.assert_not_called()
        assert not TodayNewsEdition.objects.for_team(self.team.id).exists()

    def test_the_news_needs_the_flag(self) -> None:
        with patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/today/news/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
