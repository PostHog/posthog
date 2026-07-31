from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIRequestFactory

from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.tasks.backend.facade import api as tasks_facade


class TestExperimentCleanupPr(APIBaseTest):
    def _make_request(self):
        request = APIRequestFactory().post("/fake")
        request.user = self.user
        return request

    def _running_experiment(self, repository: str | None = None) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="cleanup-test-flag",
            created_by=self.user,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 0},
                        {"key": "test", "rollout_percentage": 100},
                    ]
                }
            },
        )
        return Experiment.objects.create(
            team=self.team,
            feature_flag=flag,
            name="Cleanup test",
            created_by=self.user,
            start_date=timezone.now(),
            repository=repository,
        )

    @parameterized.expand(
        [
            # (name, flag_enabled, open_cleanup_pr, conclusion, expect_task_created)
            ("flag_on_and_opted_in", True, True, "won", True),
            ("not_opted_in", True, False, "won", False),
            ("flag_off", False, True, "won", False),
            ("no_conclusion", True, True, None, False),
        ]
    )
    @patch("products.experiments.backend.experiment_service.report_user_action")
    @patch("products.experiments.backend.experiment_service.posthoganalytics.feature_enabled")
    @patch("products.experiments.backend.experiment_service.tasks_facade.create_and_run_task")
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_cleanup_pr_fires_only_when_flag_on_and_opted_in(
        self,
        _name,
        flag_enabled,
        open_cleanup_pr,
        conclusion,
        expect_task_created,
        mock_resolve_github,
        mock_create_task,
        mock_feature_enabled,
        _mock_report,
    ):
        mock_resolve_github.return_value = SimpleNamespace(
            list_all_cached_repositories=lambda max_repos: [{"full_name": "posthog/posthog"}]
        )
        mock_feature_enabled.return_value = flag_enabled
        task_id = uuid4()
        mock_create_task.return_value = SimpleNamespace(task_id=task_id)
        experiment = self._running_experiment(repository="posthog/posthog")

        with self.captureOnCommitCallbacks(execute=True):
            ExperimentService(team=self.team, user=self.user).end_experiment(
                experiment,
                conclusion=conclusion,
                open_cleanup_pr=open_cleanup_pr,
                request=self._make_request(),
            )

        experiment.refresh_from_db()
        if expect_task_created:
            mock_create_task.assert_called_once()
            kwargs = mock_create_task.call_args.kwargs
            self.assertEqual(kwargs["origin_product"], tasks_facade.TaskOriginProduct.EXPERIMENTS)
            self.assertEqual(kwargs["repository"], "posthog/posthog")
            self.assertTrue(kwargs["create_pr"])
            self.assertEqual(experiment.flag_cleanup_task_id, task_id)
        else:
            mock_create_task.assert_not_called()
            self.assertIsNone(experiment.flag_cleanup_task_id)

    @parameterized.expand(
        [
            # (name, experiment_repository, cached_repos, expected_repository or None for skip)
            (
                "explicit_field_wins",
                "acme/monorepo",
                [{"full_name": "acme/monorepo"}, {"full_name": "acme/web"}],
                "acme/monorepo",
            ),
            ("explicit_case_insensitive", "acme/monorepo", [{"full_name": "Acme/Monorepo"}], "Acme/Monorepo"),
            ("explicit_not_in_installation_skips", "evil/other", [{"full_name": "acme/web"}], None),
            ("single_cached_repo", None, [{"full_name": "acme/web"}], "acme/web"),
            ("multiple_repos_skips", None, [{"full_name": "acme/web"}, {"full_name": "acme/api"}], None),
            ("no_github_integration", None, None, None),
            ("explicit_but_no_integration_skips", "acme/monorepo", None, None),
        ]
    )
    @patch("products.experiments.backend.experiment_service.report_user_action")
    @patch("products.experiments.backend.experiment_service.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.experiments.backend.experiment_service.tasks_facade.create_and_run_task")
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_cleanup_repository_resolution(
        self,
        _name,
        experiment_repository,
        cached_repos,
        expected_repository,
        mock_resolve_github,
        mock_create_task,
        _mock_feature_enabled,
        _mock_report,
    ):
        if cached_repos is None:
            mock_resolve_github.return_value = None
        else:
            mock_resolve_github.return_value = SimpleNamespace(
                list_all_cached_repositories=lambda max_repos: cached_repos
            )
        mock_create_task.return_value = SimpleNamespace(task_id=uuid4())
        experiment = self._running_experiment(repository=experiment_repository)

        with self.captureOnCommitCallbacks(execute=True):
            ExperimentService(team=self.team, user=self.user).end_experiment(
                experiment,
                conclusion="won",
                open_cleanup_pr=True,
                request=self._make_request(),
            )

        experiment.refresh_from_db()
        if expected_repository is None:
            mock_create_task.assert_not_called()
            self.assertIsNone(experiment.flag_cleanup_task_id)
        else:
            self.assertEqual(mock_create_task.call_args.kwargs["repository"], expected_repository)
            self.assertIsNotNone(experiment.flag_cleanup_task_id)

    @patch("products.experiments.backend.experiment_service.report_user_action")
    @patch("products.experiments.backend.experiment_service.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.experiments.backend.experiment_service.tasks_facade.create_and_run_task")
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_repository_picked_at_end_time_targets_the_task(
        self,
        mock_resolve_github,
        mock_create_task,
        _mock_feature_enabled,
        _mock_report,
    ):
        # Several cached repos would otherwise be ambiguous and skip the cleanup — the
        # repository picked in the end request must resolve it.
        mock_resolve_github.return_value = SimpleNamespace(
            list_all_cached_repositories=lambda max_repos: [{"full_name": "acme/web"}, {"full_name": "acme/api"}]
        )
        mock_create_task.return_value = SimpleNamespace(task_id=uuid4())
        experiment = self._running_experiment()

        with self.captureOnCommitCallbacks(execute=True):
            ExperimentService(team=self.team, user=self.user).end_experiment(
                experiment,
                conclusion="won",
                open_cleanup_pr=True,
                repository="acme/api",
                request=self._make_request(),
            )

        experiment.refresh_from_db()
        self.assertEqual(mock_create_task.call_args.kwargs["repository"], "acme/api")
        self.assertEqual(experiment.repository, "acme/api")

    @patch("products.experiments.backend.experiment_service.report_user_action")
    @patch("products.experiments.backend.experiment_service.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.experiments.backend.experiment_service.tasks_facade.create_and_run_task")
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_repository_outside_the_installation_skips_and_is_not_persisted(
        self,
        mock_resolve_github,
        mock_create_task,
        _mock_feature_enabled,
        _mock_report,
    ):
        mock_resolve_github.return_value = SimpleNamespace(
            list_all_cached_repositories=lambda max_repos: [{"full_name": "acme/web"}, {"full_name": "acme/api"}]
        )
        experiment = self._running_experiment()

        with self.captureOnCommitCallbacks(execute=True):
            ExperimentService(team=self.team, user=self.user).end_experiment(
                experiment,
                conclusion="won",
                open_cleanup_pr=True,
                repository="evil/other",
                request=self._make_request(),
            )

        experiment.refresh_from_db()
        mock_create_task.assert_not_called()
        self.assertIsNone(experiment.repository)

    def test_cleanup_target_never_uses_personal_github_connections(self):
        # The team has no GitHub integration, but an org owner has a personal connection with
        # cached repos. The resolver's owner fallback must not surface those repo names to
        # experiment viewers, nor be used as a cleanup target.
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.OWNER
        membership.save()
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            config={"account": {"name": "someone", "type": "User"}},
            repository_cache=[{"id": 1, "name": "private-repo", "full_name": "someone/private-repo"}],
            repository_cache_updated_at=timezone.now(),
        )
        experiment = self._running_experiment()

        target = ExperimentService(team=self.team, user=self.user).get_cleanup_repository_target(experiment)

        self.assertEqual(target, {"repository": None, "source": "no_integration", "candidates": []})
