from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils.timezone import now

from parameterized import parameterized

from posthog.models.team import Team

from products.product_analytics.backend.facade.api import (
    insight_variables_for_team,
    insights_including_soft_deleted_for_team,
    measure_saved_insight_trends,
    record_insight_view,
    saved_insight_identity,
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


class TestInsightReads(BaseTest):
    def test_saved_insight_identity_excludes_deleted_and_other_team_insights(self) -> None:
        live_insight = Insight.objects.create(team=self.team, name="Live", short_id="live-rate")
        Insight.objects.create(team=self.team, name="Deleted", deleted=True, short_id="deleted-rate")
        other_team = Team.objects.create(organization=self.organization)
        Insight.objects.create(team=other_team, name="Other", short_id="other-rate")

        assert saved_insight_identity(team_id=self.team.pk, reference="live-rate") is not None
        assert saved_insight_identity(team_id=self.team.pk, reference="deleted-rate") is None
        assert saved_insight_identity(team_id=self.team.pk, reference="other-rate") is None
        assert saved_insight_identity(team_id=self.team.pk, reference=live_insight.pk) is not None

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


class TestSavedInsightMeasurement(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Signups", short_id="signup-rate")
        self.query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "signed_up", "math": "total"}],
            "interval": "day",
        }

    def _measure(
        self,
        *,
        last_modified_at: datetime | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ):
        return measure_saved_insight_trends(
            team_id=self.team.id,
            insight_id=self.insight.id,
            short_id=self.insight.short_id,
            last_modified_at=last_modified_at if last_modified_at is not None else self.insight.last_modified_at,
            frozen_query=self.query,
            date_from=date_from if date_from is not None else now(),
            date_to=date_to if date_to is not None else now(),
        )

    @parameterized.expand([("wrong_team",), ("deleted",), ("authority_changed",)])
    @patch("posthog.api.services.query.process_query_model")
    def test_measurement_authority_failures_do_not_execute_a_query(self, failure: str, query) -> None:
        if failure == "wrong_team":
            team = Team.objects.create(organization=self.organization)
            result = measure_saved_insight_trends(
                team_id=team.id,
                insight_id=self.insight.id,
                short_id=self.insight.short_id,
                last_modified_at=self.insight.last_modified_at,
                frozen_query=self.query,
                date_from=now(),
                date_to=now(),
            )
        elif failure == "deleted":
            self.insight.deleted = True
            self.insight.save(update_fields=["deleted"])
            result = self._measure()
        else:
            result = self._measure(last_modified_at=now())

        assert result.status in {"insight_not_found", "insight_authority_changed"}
        query.assert_not_called()

    @parameterized.expand(
        [
            ("success", {"results": [{"count": 3}]}, "success"),
            ("malformed", {"results": [{"count": 3}, {"count": 2}]}, "response_unsupported"),
        ]
    )
    @patch("posthog.api.services.query.process_query_model")
    def test_measurement_returns_only_one_finite_total(self, _name: str, response: dict, status: str, query) -> None:
        query.return_value = response

        result = self._measure()

        assert result.status == status
        if status == "success":
            assert result.value == 3

    @patch("posthog.api.services.query.process_query_model", side_effect=RuntimeError())
    def test_measurement_hides_query_errors(self, query) -> None:
        assert self._measure().status == "query_error"
        query.assert_called_once()

    @patch("posthog.api.services.query.process_query_model")
    def test_measurement_uses_all_and_only_the_calendar_aligned_observed_dates(self, query) -> None:
        query.return_value = {"results": [{"count": 3}]}

        result = self._measure(
            date_from=datetime(2026, 9, 8, tzinfo=UTC),
            date_to=datetime(2026, 9, 14, 23, 59, 59, 999999, tzinfo=UTC),
        )

        assert result.status == "success"
        executed_query = query.call_args.args[1]
        assert executed_query.dateRange is not None
        assert executed_query.dateRange.date_from == "2026-09-08"
        assert executed_query.dateRange.date_to == "2026-09-14"
