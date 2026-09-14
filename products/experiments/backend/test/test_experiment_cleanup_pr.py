from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIRequestFactory

from posthog.models.organization import OrganizationMembership
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.user_integration import UserIntegration

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.tasks.backend.facade import api as tasks_facade


class TestExperimentCleanupPr(APIBaseTest):
    def _make_request(self):
        request = APIRequestFactory().post("/fake")
        request.user = self.user
        return request

    def _running_experiment(self, repository: str | None = None, flag_key: str = "cleanup-test-flag") -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=flag_key,
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
            # (name, flag_enabled, open_cleanup_pr, conclusion, expect_task_created, expected_skip_reason)
            ("flag_on_and_opted_in", True, True, "won", True, None),
            ("not_opted_in", True, False, "won", False, None),
            ("flag_off", False, True, "won", False, "flag_disabled"),
            ("no_conclusion", True, True, None, False, "no_conclusion"),
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
        expected_skip_reason,
        mock_resolve_github,
        mock_create_task,
        mock_feature_enabled,
        mock_report,
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

        completed_calls = [call for call in mock_report.call_args_list if call.args[1] == "experiment completed"]
        self.assertEqual(len(completed_calls), 1)
        completed_metadata = completed_calls[0].args[2]
        self.assertEqual(completed_metadata["open_cleanup_pr"], open_cleanup_pr)
        self.assertEqual(completed_metadata["cleanup_task_attempted"], expect_task_created)
        self.assertEqual(completed_metadata["cleanup_skip_reason"], expected_skip_reason)

        requested_calls = [
            call for call in mock_report.call_args_list if call.args[1] == "experiment cleanup pr requested"
        ]
        if expect_task_created:
            self.assertEqual(len(requested_calls), 1)
            requested_metadata = requested_calls[0].args[2]
            self.assertEqual(requested_metadata["repository_source"], "explicit")
            self.assertEqual(requested_metadata["conclusion"], "won")
            self.assertTrue(requested_metadata["confident"])
            self.assertEqual(completed_metadata["cleanup_repository_source"], "explicit")
        else:
            self.assertEqual(requested_calls, [])

    @parameterized.expand(
        [
            # (name, experiment_repository, team_default, cached_repos, expected_repository or None for skip)
            (
                "explicit_field_wins",
                "acme/monorepo",
                None,
                [{"full_name": "acme/monorepo"}, {"full_name": "acme/web"}],
                "acme/monorepo",
            ),
            ("explicit_case_insensitive", "acme/monorepo", None, [{"full_name": "Acme/Monorepo"}], "Acme/Monorepo"),
            ("explicit_not_in_installation_skips", "evil/other", None, [{"full_name": "acme/web"}], None),
            ("single_cached_repo", None, None, [{"full_name": "acme/web"}], "acme/web"),
            ("multiple_repos_skips", None, None, [{"full_name": "acme/web"}, {"full_name": "acme/api"}], None),
            ("no_github_integration", None, None, None, None),
            ("explicit_but_no_integration_skips", "acme/monorepo", None, None, None),
            (
                "team_default_resolves_multi_repo",
                None,
                "acme/api",
                [{"full_name": "acme/web"}, {"full_name": "acme/api"}],
                "acme/api",
            ),
            (
                "explicit_beats_team_default",
                "acme/web",
                "acme/api",
                [{"full_name": "acme/web"}, {"full_name": "acme/api"}],
                "acme/web",
            ),
            (
                "stale_explicit_does_not_fall_to_team_default",
                "gone/repo",
                "acme/api",
                [{"full_name": "acme/web"}, {"full_name": "acme/api"}],
                None,
            ),
            (
                "stale_team_default_falls_through_to_single_repo",
                None,
                "gone/repo",
                [{"full_name": "acme/web"}],
                "acme/web",
            ),
            (
                "stale_team_default_multi_repo_skips",
                None,
                "gone/repo",
                [{"full_name": "acme/web"}, {"full_name": "acme/api"}],
                None,
            ),
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
        team_default,
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
        if team_default:
            config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
            config.flag_cleanup_repository = team_default
            config.save()
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

    @parameterized.expand(
        [
            # (name, picked_repository, expect_default_saved)
            ("valid_pick_becomes_team_default", "acme/api", True),
            ("invalid_pick_does_not_become_team_default", "evil/other", False),
        ]
    )
    @patch("products.experiments.backend.experiment_service.report_user_action")
    @patch("products.experiments.backend.experiment_service.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.experiments.backend.experiment_service.tasks_facade.create_and_run_task")
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_set_repository_as_team_default(
        self,
        _name,
        picked_repository,
        expect_default_saved,
        mock_resolve_github,
        mock_create_task,
        _mock_feature_enabled,
        _mock_report,
    ):
        mock_resolve_github.return_value = SimpleNamespace(
            list_all_cached_repositories=lambda max_repos: [{"full_name": "acme/web"}, {"full_name": "acme/api"}]
        )
        mock_create_task.return_value = SimpleNamespace(task_id=uuid4())
        experiment = self._running_experiment()
        service = ExperimentService(team=self.team, user=self.user)

        with self.captureOnCommitCallbacks(execute=True):
            service.end_experiment(
                experiment,
                conclusion="won",
                open_cleanup_pr=True,
                repository=picked_repository,
                set_repository_as_team_default=True,
                request=self._make_request(),
            )

        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        if expect_default_saved:
            self.assertEqual(config.flag_cleanup_repository, picked_repository)
            # A later experiment with no repository of its own now resolves to the default.
            other = self._running_experiment(flag_key="cleanup-default-second-flag")
            target = service.get_cleanup_repository_target(other)
            self.assertEqual(target["repository"], picked_repository)
            self.assertEqual(target["source"], "team_default")
        else:
            self.assertIsNone(config.flag_cleanup_repository)
            mock_create_task.assert_not_called()

    @patch("products.experiments.backend.experiment_service.report_user_action")
    @patch("products.experiments.backend.experiment_service.posthoganalytics.feature_enabled", return_value=True)
    @patch(
        "products.experiments.backend.experiment_service.tasks_facade.create_and_run_task",
        side_effect=Exception("sandbox unavailable"),
    )
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_team_default_not_saved_when_task_creation_fails(
        self,
        mock_resolve_github,
        _mock_create_task,
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
                repository="acme/api",
                set_repository_as_team_default=True,
                request=self._make_request(),
            )

        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        self.assertIsNone(config.flag_cleanup_repository)

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


class TestExperimentsConfigFlagCleanupRepository(APIBaseTest):
    @parameterized.expand(
        [
            # (name, submitted, expected_status, expected_stored)
            ("valid_repo_stored_lowercased", "posthog/POSTHOG", 200, "posthog/posthog"),
            ("repo_outside_installation", "other/repo", 400, "posthog/existing"),
            ("malformed_repo", "not-a-repo", 400, "posthog/existing"),
            ("null_clears", None, 200, None),
            ("empty_string_clears", "", 200, None),
        ]
    )
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_flag_cleanup_repository_validation(
        self, _name, submitted, expected_status, expected_stored, mock_resolve_github
    ):
        mock_resolve_github.return_value = SimpleNamespace(
            list_all_cached_repositories=lambda max_repos: [{"full_name": "PostHog/posthog"}]
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.flag_cleanup_repository = "posthog/existing"
        config.save()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/experiments_config/",
            {"flag_cleanup_repository": submitted},
        )

        self.assertEqual(response.status_code, expected_status, response.json())
        config.refresh_from_db()
        self.assertEqual(config.flag_cleanup_repository, expected_stored)
        if expected_status == 200:
            self.assertEqual(response.json()["flag_cleanup_repository"], expected_stored)
