from datetime import datetime

from posthog.test.base import BaseTest

from django.utils.timezone import now

from parameterized import parameterized

from posthog.models.team import Team
from posthog.test.db_context_capturing import capture_db_queries

from products.product_analytics.backend.facade.api import (
    insight_variables_for_team,
    record_insight_view,
    record_insight_views,
)
from products.product_analytics.backend.models.insight import Insight, InsightViewed
from products.product_analytics.backend.models.insight_variable import InsightVariable


class TestInsightVariableReads(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.variable = InsightVariable.objects.create(
            team=self.team, name="Country", code_name="country", type="String"
        )

    @parameterized.expand([("root_team",), ("environment_team",)])
    def test_variables_are_visible_from_the_whole_project(self, which_team: str) -> None:
        team = self.team
        if which_team == "environment_team":
            team = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)

        assert [variable.code_name for variable in insight_variables_for_team(team.pk)] == ["country"]

    def test_a_team_in_another_project_sees_none_of_them(self) -> None:
        other_team = Team.objects.create(organization=self.organization)

        assert insight_variables_for_team(other_team.pk) == []


class TestRecordInsightView(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Signups")

    @parameterized.expand([("anonymous", False), ("identified", True)])
    def test_viewing_twice_moves_the_timestamp_instead_of_adding_a_row(self, _name: str, identified: bool) -> None:
        viewer = {"team_id": self.team.pk, "user_id": self.user.pk} if identified else {}

        record_insight_view(insight_id=self.insight.pk, **viewer)
        first = InsightViewed.objects.get(insight_id=self.insight.pk)
        record_insight_view(insight_id=self.insight.pk, **viewer)

        assert InsightViewed.objects.filter(insight_id=self.insight.pk).count() == 1
        assert InsightViewed.objects.get(insight_id=self.insight.pk).last_viewed_at >= first.last_viewed_at

    def test_an_anonymous_view_does_not_replace_a_users_view(self) -> None:
        InsightViewed.objects.create(team=self.team, user=self.user, insight=self.insight, last_viewed_at=now())

        record_insight_view(insight_id=self.insight.pk)

        assert InsightViewed.objects.filter(insight_id=self.insight.pk).count() == 2


class TestRecordInsightViews(BaseTest):
    def _upsert_sql(self, insight_ids: list[int], viewed_at: datetime) -> str:
        with capture_db_queries() as captured:
            record_insight_views(
                team_id=self.team.pk,
                user_id=self.user.pk,
                last_viewed_at_by_insight_id=dict.fromkeys(insight_ids, viewed_at),
            )
        return next(query["sql"] for query in captured.captured_queries if "posthog_insightviewed" in query["sql"])

    def test_the_batch_locks_the_rows_in_the_same_order_whatever_order_the_ids_arrive_in(self) -> None:
        insight_ids = [Insight.objects.create(team=self.team, name=f"Signups {i}").pk for i in range(3)]
        viewed_at = now()

        assert self._upsert_sql(list(reversed(insight_ids)), viewed_at) == self._upsert_sql(insight_ids, viewed_at)
