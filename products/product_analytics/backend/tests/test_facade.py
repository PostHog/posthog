from datetime import timedelta

from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now

from parameterized import parameterized

from posthog.models.team import Team
from posthog.models.user import User

from products.product_analytics.backend.facade.api import (
    insight_variables_for_team,
    insights_including_soft_deleted_for_team,
    recent_unique_viewer_counts_by_insight,
    record_insight_view,
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

    @parameterized.expand([("unviewed_insight", False), ("other_team_insight", True)])
    def test_recent_unique_viewer_counts_are_scoped_to_the_requested_recent_views(
        self, _name: str, include_other_team_insight: bool
    ) -> None:
        since = now() - timedelta(days=7)
        second_viewer = User.objects.create_user(
            email="second-viewer@example.com", first_name="Second", password="password"
        )
        old_viewer = User.objects.create_user(email="old-viewer@example.com", first_name="Old", password="password")
        other_team = Team.objects.create(organization=self.organization)
        unviewed_insight = Insight.objects.create(team=self.team, name="Unviewed")
        unrequested_insight = Insight.objects.create(team=self.team, name="Unrequested")
        other_team_insight = Insight.objects.create(team=other_team, name="Other team")

        record_insight_view(insight_id=self.insight.pk, team_id=self.team.pk, user_id=self.user.pk)
        record_insight_view(insight_id=self.insight.pk, team_id=self.team.pk, user_id=self.user.pk)
        InsightViewed.objects.bulk_create(
            [
                InsightViewed(team=self.team, user=second_viewer, insight=self.insight, last_viewed_at=now()),
                InsightViewed(
                    team=self.team,
                    user=old_viewer,
                    insight=self.insight,
                    last_viewed_at=since - timedelta(microseconds=1),
                ),
                InsightViewed(team=self.team, insight=self.insight, last_viewed_at=now()),
                InsightViewed(team=self.team, user=self.user, insight=unrequested_insight, last_viewed_at=now()),
                InsightViewed(team=other_team, user=second_viewer, insight=other_team_insight, last_viewed_at=now()),
            ]
        )
        insight_ids = {self.insight.pk, other_team_insight.pk if include_other_team_insight else unviewed_insight.pk}

        with CaptureQueriesContext(connection) as queries:
            counts = recent_unique_viewer_counts_by_insight(
                team_id=self.team.pk,
                insight_ids=insight_ids,
                since=since,
            )

        assert len(queries) == 1
        assert 'COUNT(DISTINCT "posthog_insightviewed"."user_id")' in queries[0]["sql"]
        assert counts == {self.insight.pk: 2}


class TestInsightReads(BaseTest):
    def test_including_soft_deleted_insights_stays_scoped_to_the_team(self) -> None:
        deleted_insight = Insight.objects.create(team=self.team, name="Deleted", deleted=True)
        live_insight = Insight.objects.create(team=self.team, name="Live")
        other_team = Team.objects.create(organization=self.organization)
        other_team_insight = Insight.objects.create(team=other_team, name="Other team")

        insights = insights_including_soft_deleted_for_team(
            team_id=self.team.pk,
            insight_ids={deleted_insight.pk, live_insight.pk, other_team_insight.pk},
        )

        assert {insight.pk for insight in insights} == {deleted_insight.pk, live_insight.pk}
