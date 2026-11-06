import json
from datetime import UTC, date, datetime, timedelta
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
from posthog.models.activity_logging.activity_log import ActivityLog

from products.today.backend.facade.contracts import NewsFact
from products.today.backend.facade.enums import NewsTone
from products.today.backend.logic.news import editions, writer
from products.today.backend.logic.news.facts import ScoredFact, enough
from products.today.backend.models import TodayHighlights, TodayNewsEdition
from products.today.backend.temporal.inputs import GenerateNewsInputs
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def fact(key: str, **overrides: Any) -> NewsFact:
    values: dict[str, Any] = {
        "key": key,
        "kind": "metric_moved",
        "title": f"Metric {key}",
        "importance": 0.75,
        "magnitude": 1.0,
        "breadth": 1.0,
        "at": NOW,
        "tone": NewsTone.NEUTRAL,
        "resource": "insight",
        "scopes": ("insight:read",),
        "object_id": key,
        "product": "product_analytics",
        **overrides,
    }
    return NewsFact(**values)


def scored(*scores: float) -> list[ScoredFact]:
    return [ScoredFact(fact=fact(f"metric:{index}"), score=value) for index, value in enumerate(scores)]


def completion(reply: dict[str, Any]) -> MagicMock:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))],
        model="claude-haiku-4-5",
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=200),
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response
    build = MagicMock()
    build.return_value.with_options.return_value = client
    return build


def story(ref: str, title: str = "Signups fell after the pricing change") -> dict[str, str]:
    return {"ref": ref, "title": title, "summary": "Fewer people finished signup.", "dive_prompt": "Why?"}


class TestNewsRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("three strong facts", (0.5, 0.5, 0.5), True),
            ("two strong facts", (0.7, 0.6, 0.3), False),
            ("one lead and two supporting facts", (0.8, 0.45, 0.4), True),
            ("one lead and one supporting fact", (0.8, 0.45, 0.39), False),
            ("no facts", (), False),
        ]
    )
    def test_enough_strong_facts(self, _name: str, scores: tuple[float, ...], expected: bool) -> None:
        assert enough(scored(*scores)) is expected

    def test_the_model_picks_refs_and_the_facts_fill_the_numbers(self) -> None:
        facts = [
            ScoredFact(
                fact=fact(
                    "metric:signups",
                    title="Signups",
                    change=-12.5,
                    tone=NewsTone.RISK,
                    metric_label="Signups per day",
                    metric_value="1,204",
                    series=(10.0, 9.0, 8.0),
                    series_labels=("Mon", "Tue", "Wed"),
                    url="/insights/abc",
                ),
                score=0.75,
            ),
            ScoredFact(fact=fact("flag:7", title="New onboarding", product="feature_flags"), score=0.5),
            ScoredFact(fact=fact("flag:8", title="Dark mode", product="feature_flags"), score=0.4),
        ]
        reply = {
            "lead": {**story("f1"), "change": 99, "dive_prompt": "See https://example.com"},
            "stories": [story("f2"), story("f42"), story("f1"), story("f3", "Read www.example.com now")],
            "briefs": [{"refs": ["f3"], "text": "Dark mode reached everyone."}, {"refs": ["f9"], "text": "Made up."}],
        }

        built = writer.build_edition(reply, facts)

        assert built is not None
        assert (built.lead.id, built.lead.change, built.lead.tone, built.lead.url) == (
            "metric:signups",
            -12.5,
            NewsTone.RISK,
            "/insights/abc",
        )
        assert (built.lead.metric_value, built.lead.series, built.lead.series_labels) == (
            "1,204",
            [10.0, 9.0, 8.0],
            ["Mon", "Tue", "Wed"],
        )
        assert "example.com" not in built.lead.dive_prompt
        assert [item.id for item in built.stories] == ["flag:7"]
        assert built.stories[0].product_label == "Feature flags"
        assert [brief.refs for brief in built.briefs] == [("flag:8",)]

    def test_a_viewer_never_sees_a_story_or_brief_about_a_hidden_object(self) -> None:
        facts = [
            ScoredFact(fact=fact("metric:hidden", metric_value="9", series=(1.0, 2.0)), score=0.8),
            ScoredFact(fact=fact("metric:shown", metric_value="3", series=(4.0, 5.0)), score=0.6),
        ]
        reply = {
            "lead": story("f1"),
            "stories": [story("f2")],
            "briefs": [{"refs": ["f1", "f2"], "text": "Both moved."}, {"refs": ["f2"], "text": "One moved."}],
        }
        built = writer.build_edition(reply, facts)
        assert built is not None

        shown = editions.visible_edition(
            built,
            {item.fact.key: item.fact for item in facts},
            lambda candidate: candidate.key != "metric:hidden",
            edition_id="edition-1",
            start=date(2026, 11, 2),
        )

        assert shown is not None
        assert (shown.lead.id, shown.lead.metric_value, shown.lead.series) == ("metric:shown", "3", [4.0, 5.0])
        assert (shown.stories, shown.briefs) == ([], ["One moved."])


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

    def _end_experiment(self, item_id: str, name: str) -> None:
        for user in (self.user, self.teammate):
            ActivityLog.objects.create(
                team_id=self.team.id,
                organization_id=self.organization.id,
                user=user,
                scope="Experiment",
                item_id=item_id,
                activity="updated",
                created_at=NOW - timedelta(days=1),
                detail={"name": name, "changes": [{"type": "Experiment", "action": "changed", "field": "end_date"}]},
            )

    def _get(self, connect: MagicMock) -> dict[str, Any]:
        with (
            patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=True),
            patch.object(editions, "sync_connect", connect),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/today/news/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _connect(self) -> MagicMock:
        connect = MagicMock()
        connect.return_value.start_workflow = AsyncMock()
        return connect

    def test_the_first_request_starts_one_edition_and_a_later_one_serves_it(self) -> None:
        for item_id, name in (("1", "Pricing page"), ("2", "Checkout copy"), ("3", "Onboarding steps")):
            self._end_experiment(item_id, name)
        connect = self._connect()

        assert self._get(connect) == {"status": "computing", "skip_reason": None, "edition": None}
        assert self._get(connect)["status"] == "computing"
        assert connect.return_value.start_workflow.await_count == 1
        inputs: GenerateNewsInputs = connect.return_value.start_workflow.call_args.args[1]

        assert editions.collect_facts(inputs) is True
        reply = {"lead": story("f2"), "stories": [story("f1"), story("f7")], "briefs": []}
        with patch.object(writer, "build_openai_client", completion(reply)):
            editions.write_edition(inputs)
        body = self._get(connect)

        assert body["status"] == "ready"
        assert body["edition"]["id"] == inputs.edition_id
        assert (body["edition"]["lead"]["id"], body["edition"]["lead"]["url"]) == ("experiment:2", "/experiments/2")
        assert [item["id"] for item in body["edition"]["stories"]] == ["experiment:1"]
        assert connect.return_value.start_workflow.await_count == 1

    def test_a_quiet_week_is_skipped_without_a_model_call(self) -> None:
        self._end_experiment("1", "Pricing page")
        connect = self._connect()
        self._get(connect)
        inputs: GenerateNewsInputs = connect.return_value.start_workflow.call_args.args[1]
        build = completion({})

        with patch.object(writer, "build_openai_client", build):
            proceed = editions.collect_facts(inputs)

        assert proceed is False
        build.assert_not_called()
        assert self._get(connect) == {"status": "skipped", "skip_reason": "quiet", "edition": None}
        row = TodayNewsEdition.objects.for_team(self.team.id).get(id=inputs.edition_id)
        assert [item["fact"]["key"] for item in row.facts] == ["experiment:1"]

    @parameterized.expand([("ai not approved", "ai_not_approved"), ("one person uses today", "few_people")])
    def test_a_failed_gate_starts_nothing(self, _name: str, reason: str) -> None:
        if reason == "ai_not_approved":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save()
        else:
            TodayHighlights.objects.for_team(self.team.id).filter(user_id=self.teammate.id).delete()
        connect = self._connect()

        assert self._get(connect) == {"status": "skipped", "skip_reason": reason, "edition": None}
        connect.return_value.start_workflow.assert_not_called()
        assert not TodayNewsEdition.objects.for_team(self.team.id).exists()

    def test_the_news_needs_the_flag(self) -> None:
        with patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/today/news/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
