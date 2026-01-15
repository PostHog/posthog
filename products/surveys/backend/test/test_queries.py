from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from posthog.models import Experiment, FeatureFlag, Insight, User
from posthog.models.insight import InsightViewed

from products.surveys.backend.queries import (
    get_insight_type,
    get_most_viewed_funnels,
    get_most_viewed_trends,
    get_recently_concluded_experiments,
    get_recently_rolled_out_flags,
    get_running_experiments,
    get_survey_recommendation_candidates,
)


class TestGetMostViewedFunnels(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.test_users = [self.user]
        for i in range(9):
            user = User.objects.create_and_join(
                organization=self.organization,
                email=f"test_user_{i}@posthog.com",
                password="testpassword",
            )
            self.test_users.append(user)

    def _create_funnel_insight(self, name: str, query: dict | None = None) -> Insight:
        if query is None:
            query = {
                "kind": "FunnelsQuery",
                "series": [
                    {"kind": "EventsNode", "event": "$pageview"},
                    {"kind": "EventsNode", "event": "sign_up"},
                ],
            }
        return Insight.objects.create(team=self.team, name=name, saved=True, query=query)

    def _create_trend_insight(self, name: str) -> Insight:
        return Insight.objects.create(
            team=self.team,
            name=name,
            saved=True,
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
        )

    def _record_views(self, insight: Insight, count: int, days_ago: int = 0) -> None:
        for i in range(min(count, len(self.test_users))):
            InsightViewed.objects.update_or_create(
                team=self.team,
                user=self.test_users[i],
                insight=insight,
                defaults={"last_viewed_at": timezone.now() - timedelta(days=days_ago)},
            )

    def test_returns_empty_list_when_no_funnels(self) -> None:
        result = get_most_viewed_funnels(self.team)
        assert result == []

    def test_returns_empty_list_when_funnels_not_viewed(self) -> None:
        self._create_funnel_insight("Unviewed funnel")
        result = get_most_viewed_funnels(self.team)
        assert result == []

    def test_returns_viewed_funnels_ordered_by_view_count(self) -> None:
        funnel1 = self._create_funnel_insight("Popular funnel")
        funnel2 = self._create_funnel_insight("Less popular funnel")
        funnel3 = self._create_funnel_insight("Medium funnel")

        self._record_views(funnel1, count=10)
        self._record_views(funnel2, count=2)
        self._record_views(funnel3, count=5)

        result = get_most_viewed_funnels(self.team)

        assert len(result) == 3
        assert result[0]["insight_name"] == "Popular funnel"
        assert result[0]["view_count"] == 10
        assert result[1]["insight_name"] == "Medium funnel"
        assert result[1]["view_count"] == 5
        assert result[2]["insight_name"] == "Less popular funnel"
        assert result[2]["view_count"] == 2

    def test_excludes_non_funnel_insights(self) -> None:
        funnel = self._create_funnel_insight("Funnel insight")
        trend = self._create_trend_insight("Trend insight")

        self._record_views(funnel, count=5)
        self._record_views(trend, count=10)

        result = get_most_viewed_funnels(self.team)

        assert len(result) == 1
        assert result[0]["insight_name"] == "Funnel insight"

    def test_excludes_views_outside_time_window(self) -> None:
        funnel = self._create_funnel_insight("Recent funnel")
        old_funnel = self._create_funnel_insight("Old funnel")

        self._record_views(funnel, count=5, days_ago=10)
        self._record_views(old_funnel, count=10, days_ago=40)

        result = get_most_viewed_funnels(self.team, days=30)

        assert len(result) == 1
        assert result[0]["insight_name"] == "Recent funnel"

    def test_respects_limit(self) -> None:
        for i in range(5):
            funnel = self._create_funnel_insight(f"Funnel {i}")
            self._record_views(funnel, count=5 - i)

        result = get_most_viewed_funnels(self.team, limit=3)

        assert len(result) == 3

    def test_handles_insight_viz_node_wrapper(self) -> None:
        query = {
            "kind": "InsightVizNode",
            "source": {
                "kind": "FunnelsQuery",
                "series": [
                    {"kind": "EventsNode", "event": "page_load"},
                    {"kind": "EventsNode", "event": "click"},
                ],
            },
        }
        funnel = self._create_funnel_insight("Wrapped funnel", query=query)
        self._record_views(funnel, count=3)

        result = get_most_viewed_funnels(self.team)

        assert len(result) == 1
        assert result[0]["insight_name"] == "Wrapped funnel"
        assert result[0]["insight_type"] == "funnel"


class TestGetMostViewedTrends(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.test_users = [self.user]
        for i in range(9):
            user = User.objects.create_and_join(
                organization=self.organization,
                email=f"trend_test_user_{i}@posthog.com",
                password="testpassword",
            )
            self.test_users.append(user)

    def _create_trend_insight(self, name: str) -> Insight:
        return Insight.objects.create(
            team=self.team,
            name=name,
            saved=True,
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
        )

    def _record_views(self, insight: Insight, count: int) -> None:
        for i in range(min(count, len(self.test_users))):
            InsightViewed.objects.update_or_create(
                team=self.team,
                user=self.test_users[i],
                insight=insight,
                defaults={"last_viewed_at": timezone.now()},
            )

    def test_returns_viewed_trends(self) -> None:
        trend = self._create_trend_insight("My trend")
        self._record_views(trend, count=5)

        result = get_most_viewed_trends(self.team)

        assert len(result) == 1
        assert result[0]["insight_name"] == "My trend"
        assert result[0]["insight_type"] == "trend"


class TestGetRecentlyConcludedExperiments(APIBaseTest):
    def test_returns_concluded_experiments(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="test-exp-flag", created_by=self.user)
        Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=30),
            end_date=timezone.now() - timedelta(days=5),
        )

        result = get_recently_concluded_experiments(self.team)

        assert len(result) == 1
        assert result[0]["experiment_name"] == "Test Experiment"
        assert result[0]["is_complete"] is True

    def test_excludes_old_experiments(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="old-exp-flag", created_by=self.user)
        Experiment.objects.create(
            team=self.team,
            name="Old Experiment",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=120),
            end_date=timezone.now() - timedelta(days=90),
        )

        result = get_recently_concluded_experiments(self.team, days=60)

        assert len(result) == 0


class TestGetRunningExperiments(APIBaseTest):
    def test_returns_running_experiments(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="running-exp-flag", created_by=self.user)
        Experiment.objects.create(
            team=self.team,
            name="Running Experiment",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=5),
            end_date=None,
        )

        result = get_running_experiments(self.team)

        assert len(result) == 1
        assert result[0]["experiment_name"] == "Running Experiment"
        assert result[0]["is_complete"] is False


class TestGetRecentlyRolledOutFlags(APIBaseTest):
    def test_returns_fully_rolled_out_flags(self) -> None:
        FeatureFlag.objects.create(
            team=self.team,
            key="new-feature",
            name="New Feature Flag",
            created_by=self.user,
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        result = get_recently_rolled_out_flags(self.team)

        assert len(result) == 1
        assert result[0]["flag_key"] == "new-feature"
        assert result[0]["is_fully_rolled_out"] is True

    def test_excludes_partially_rolled_out_flags(self) -> None:
        FeatureFlag.objects.create(
            team=self.team,
            key="partial-feature",
            created_by=self.user,
            active=True,
            filters={"groups": [{"rollout_percentage": 50}]},
        )

        result = get_recently_rolled_out_flags(self.team)

        assert len(result) == 0


class TestGetInsightType(APIBaseTest):
    def test_identifies_funnel_query(self) -> None:
        assert get_insight_type({"kind": "FunnelsQuery"}) == "funnel"

    def test_identifies_trend_query(self) -> None:
        assert get_insight_type({"kind": "TrendsQuery"}) == "trend"

    def test_identifies_wrapped_query(self) -> None:
        assert get_insight_type({"kind": "InsightVizNode", "source": {"kind": "RetentionQuery"}}) == "retention"

    def test_returns_unknown_for_unrecognized(self) -> None:
        assert get_insight_type({"kind": "SomeNewQuery"}) == "unknown"


class TestGetSurveyRecommendationCandidates(APIBaseTest):
    def test_returns_all_candidate_types(self) -> None:
        result = get_survey_recommendation_candidates(self.team)

        assert "most_viewed_funnels" in result
        assert "most_viewed_trends" in result
        assert "concluded_experiments" in result
        assert "running_experiments" in result
        assert "rolled_out_flags" in result
