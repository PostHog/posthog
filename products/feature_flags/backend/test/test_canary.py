from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from prometheus_client import CollectorRegistry

from posthog.tasks.test.utils import PushGatewayTaskTestMixin
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.feature_flags.backend.canary import run_local_eval_canary
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.tasks import feature_flags_local_eval_canary_task

_PRESENT_GAUGE = "posthog_feature_flags_local_eval_canary_group_mapping_present"
_FAILURE_COUNTER = "posthog_feature_flags_local_eval_canary_failure_total"


class TestLocalEvalCanary(BaseTest):
    def setUp(self):
        super().setUp()
        self.registry = CollectorRegistry()

    def _present(self) -> float | None:
        return self.registry.get_sample_value(_PRESENT_GAUGE)

    def _failures(self) -> float | None:
        return self.registry.get_sample_value(_FAILURE_COUNTER)

    def test_no_op_when_team_id_unset(self):
        with override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=None):
            run_local_eval_canary(self.registry)

        # No metrics registered when the canary is not configured
        assert self._present() is None
        assert self._failures() is None

    def test_healthy_team_marks_mapping_present(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        with override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=self.team.id):
            run_local_eval_canary(self.registry)

        assert self._present() == 1
        assert self._failures() == 0

    def test_empty_mapping_marks_absent_and_fails(self):
        # Team with no group types, so the mapping is empty
        with override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=self.team.id):
            run_local_eval_canary(self.registry)

        assert self._present() == 0
        assert self._failures() == 1

    def test_unresolved_group_flag_fails_even_with_mapping_present(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        # Flag aggregates on an index absent from the mapping, so it cannot resolve
        FeatureFlag.objects.create(
            team=self.team,
            key="orphan-group-flag",
            filters={"aggregation_group_type_index": 1, "groups": [{"rollout_percentage": 100}]},
        )

        with override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=self.team.id):
            run_local_eval_canary(self.registry)

        assert self._present() == 1  # the mapping itself is non-empty
        assert self._failures() == 1  # but a group flag can't resolve

    def test_missing_team_marks_absent_and_fails(self):
        with override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=2_000_000_000):
            run_local_eval_canary(self.registry)

        assert self._present() == 0
        assert self._failures() == 1

    def test_build_failure_marks_absent_and_fails(self):
        # A build exception is the exact failure the canary exists to catch: it must
        # mark the mapping absent and count a failure, not report healthy.
        with (
            override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=self.team.id),
            patch(
                "products.feature_flags.backend.canary._get_flags_response_for_local_evaluation",
                side_effect=Exception("boom"),
            ),
        ):
            run_local_eval_canary(self.registry)

        assert self._present() == 0
        assert self._failures() == 1


@override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=None)
class TestLocalEvalCanaryTask(PushGatewayTaskTestMixin, BaseTest):
    @patch("products.feature_flags.backend.tasks.run_local_eval_canary")
    def test_task_no_ops_when_unset(self, mock_run):
        feature_flags_local_eval_canary_task()
        mock_run.assert_not_called()

    @patch("products.feature_flags.backend.tasks.run_local_eval_canary")
    def test_task_runs_canary_when_configured(self, mock_run):
        with override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=self.team.id):
            feature_flags_local_eval_canary_task()
        mock_run.assert_called_once()

    @patch("products.feature_flags.backend.tasks.run_local_eval_canary")
    def test_task_skips_when_lock_held(self, mock_run):
        from django.core.cache import cache as django_cache

        lock_key = "posthog:feature_flags_local_eval_canary:lock"
        django_cache.add(lock_key, "locked", timeout=60)
        try:
            with override_settings(FEATURE_FLAGS_CANARY_TEAM_ID=self.team.id):
                feature_flags_local_eval_canary_task()
            mock_run.assert_not_called()
        finally:
            django_cache.delete(lock_key)
