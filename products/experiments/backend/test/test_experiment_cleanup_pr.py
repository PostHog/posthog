from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIRequestFactory

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.tasks.backend.facade import api as tasks_facade


class TestExperimentCleanupPr(APIBaseTest):
    def _make_request(self):
        request = APIRequestFactory().post("/fake")
        request.user = self.user
        return request

    def _running_experiment(self) -> Experiment:
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
    def test_cleanup_pr_fires_only_when_flag_on_and_opted_in(
        self,
        _name,
        flag_enabled,
        open_cleanup_pr,
        conclusion,
        expect_task_created,
        mock_create_task,
        mock_feature_enabled,
        _mock_report,
    ):
        mock_feature_enabled.return_value = flag_enabled
        task_id = uuid4()
        mock_create_task.return_value = SimpleNamespace(task_id=task_id)
        experiment = self._running_experiment()

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
            self.assertEqual(kwargs["repository"], "PostHog/posthog")
            self.assertTrue(kwargs["create_pr"])
            self.assertEqual(experiment.flag_cleanup_task_id, task_id)
        else:
            mock_create_task.assert_not_called()
            self.assertIsNone(experiment.flag_cleanup_task_id)
