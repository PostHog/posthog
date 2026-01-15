from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import FeatureFlag, Organization, Team

from products.surveys.backend.models import SurveyRecommendation
from products.surveys.backend.tasks import (
    cleanup_stale_recommendations,
    generate_survey_recommendations_for_all_teams,
    generate_survey_recommendations_for_team,
)


class TestCleanupStaleRecommendations(BaseTest):
    def _create_recommendation(self, **kwargs):
        defaults = {
            "team": self.team,
            "recommendation_type": SurveyRecommendation.RecommendationType.LOW_CONVERSION_FUNNEL,
            "survey_defaults": {"name": "Test"},
            "display_context": {"title": "Test"},
            "score": 50,
            "status": SurveyRecommendation.Status.ACTIVE,
        }
        defaults.update(kwargs)
        return SurveyRecommendation.objects.create(**defaults)

    def test_dismisses_recommendations_with_deleted_insight(self):
        from posthog.models import Insight

        insight = Insight.objects.create(team=self.team, deleted=True)
        rec = self._create_recommendation(source_insight=insight)

        cleanup_stale_recommendations()

        rec.refresh_from_db()
        self.assertEqual(rec.status, SurveyRecommendation.Status.DISMISSED)
        self.assertIsNotNone(rec.dismissed_at)

    def test_dismisses_recommendations_with_deleted_feature_flag(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            deleted=True,
            created_by=self.user,
        )
        rec = self._create_recommendation(source_feature_flag=flag)

        cleanup_stale_recommendations()

        rec.refresh_from_db()
        self.assertEqual(rec.status, SurveyRecommendation.Status.DISMISSED)

    def test_dismisses_old_unconverted_recommendations(self):
        from datetime import timedelta

        from django.utils import timezone

        rec = self._create_recommendation()
        SurveyRecommendation.objects.filter(id=rec.id).update(created_at=timezone.now() - timedelta(days=31))

        cleanup_stale_recommendations()

        rec.refresh_from_db()
        self.assertEqual(rec.status, SurveyRecommendation.Status.DISMISSED)

    def test_keeps_recent_recommendations(self):
        rec = self._create_recommendation()

        cleanup_stale_recommendations()

        rec.refresh_from_db()
        self.assertEqual(rec.status, SurveyRecommendation.Status.ACTIVE)


class TestGenerateSurveyRecommendationsForTeam(BaseTest):
    def test_returns_early_when_team_does_not_exist(self):
        with patch("products.surveys.backend.tasks.logger") as mock_logger:
            generate_survey_recommendations_for_team(999999)
            mock_logger.warning.assert_called_once()
            self.assertIn("Team not found", str(mock_logger.warning.call_args))

    @patch("products.surveys.backend.recommendations.generate_recommendations")
    def test_calls_generator_for_valid_team(self, mock_generate):
        mock_generate.return_value = 3

        generate_survey_recommendations_for_team(self.team.id)

        mock_generate.assert_called_once_with(self.team)

    @patch("products.surveys.backend.recommendations.generate_recommendations")
    def test_logs_error_when_generator_fails(self, mock_generate):
        mock_generate.side_effect = Exception("Test error")

        with (
            patch("products.surveys.backend.tasks.logger") as mock_logger,
            self.assertRaises(Exception),
        ):
            generate_survey_recommendations_for_team(self.team.id)
            mock_logger.exception.assert_called_once()


class TestGenerateSurveyRecommendationsForAllTeams(BaseTest):
    @patch("products.surveys.backend.tasks.generate_survey_recommendations_for_team.apply_async")
    @patch("posthoganalytics.feature_enabled")
    @patch("posthog.caching.utils.active_teams")
    def test_only_spawns_tasks_for_enabled_teams(self, mock_active_teams, mock_feature_enabled, mock_apply_async):
        org2 = Organization.objects.create(name="Org 2")
        team2 = Team.objects.create(organization=org2, name="Team 2")

        mock_active_teams.return_value = [self.team.id, team2.id]
        mock_feature_enabled.side_effect = lambda key, distinct_id, **kwargs: distinct_id == str(org2.id)

        generate_survey_recommendations_for_all_teams()

        self.assertEqual(mock_apply_async.call_count, 1)
        mock_apply_async.assert_called_with(args=[team2.id], countdown=0)

    @patch("products.surveys.backend.tasks.generate_survey_recommendations_for_team.apply_async")
    @patch("posthoganalytics.feature_enabled")
    @patch("posthog.caching.utils.active_teams")
    def test_spawns_no_tasks_when_flag_disabled_for_all(
        self, mock_active_teams, mock_feature_enabled, mock_apply_async
    ):
        mock_active_teams.return_value = [self.team.id]
        mock_feature_enabled.return_value = False

        generate_survey_recommendations_for_all_teams()

        mock_apply_async.assert_not_called()

    @patch("products.surveys.backend.tasks.generate_survey_recommendations_for_team.apply_async")
    @patch("posthoganalytics.feature_enabled")
    @patch("posthog.caching.utils.active_teams")
    def test_staggers_task_execution(self, mock_active_teams, mock_feature_enabled, mock_apply_async):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        team3 = Team.objects.create(organization=self.organization, name="Team 3")

        mock_active_teams.return_value = [self.team.id, team2.id, team3.id]
        mock_feature_enabled.return_value = True

        generate_survey_recommendations_for_all_teams()

        self.assertEqual(mock_apply_async.call_count, 3)
        calls = mock_apply_async.call_args_list
        self.assertEqual(calls[0][1]["countdown"], 0)
        self.assertEqual(calls[1][1]["countdown"], 30)
        self.assertEqual(calls[2][1]["countdown"], 60)
