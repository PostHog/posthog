from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from posthog.constants import AvailableFeature

from products.approvals.backend.exceptions import ApprovalRequired
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestExperimentServiceApprovals(APIBaseTest):
    """launch/pause/resume flip the linked flag's `active` state, which must pass through
    the FeatureFlagSerializer approval gate (action `feature_flag.enable`/`feature_flag.disable`)."""

    _METRIC = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": "m1",
        "source": {"kind": "EventsNode", "event": "$pageview"},
    }

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()

    def _service(self) -> ExperimentService:
        return ExperimentService(team=self.team, user=self.user)

    def _request(self) -> Any:
        request = APIRequestFactory().post("/fake")
        request.user = self.user
        return request

    def _create_enable_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _create_disable_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.disable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _create_update_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _create_draft_experiment(self, feature_flag_key: str) -> Experiment:
        return self._service().create_experiment(
            name="Approval Test",
            feature_flag_key=feature_flag_key,
            metrics=[self._METRIC],
            primary_metrics_ordered_uuids=["m1"],
            allow_unknown_events=True,
        )

    def _create_launched_experiment(self, feature_flag_key: str) -> Experiment:
        experiment = self._create_draft_experiment(feature_flag_key)
        # Launch without a policy in place so the flag is genuinely active afterwards.
        self._service().launch_experiment(experiment, request=self._request())
        experiment.refresh_from_db()
        return experiment

    def test_launch_under_enable_policy_requires_approval(self, _mock_enabled):
        experiment = self._create_draft_experiment("launch-gated")
        self._create_enable_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().launch_experiment(experiment, request=self._request())

        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False
        assert experiment.start_date is None

    def test_launch_under_enable_policy_without_request_requires_approval(self, _mock_enabled):
        # Internal callers (e.g. _create_running_experiment) invoke launch with request=None,
        # which builds a _ServiceRequest shim. The gate must still raise ApprovalRequired
        # rather than crashing on a missing request attribute.
        experiment = self._create_draft_experiment("launch-gated-no-request")
        self._create_enable_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().launch_experiment(experiment)

        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False
        assert experiment.start_date is None

    def test_pause_under_disable_policy_requires_approval(self, _mock_enabled):
        experiment = self._create_launched_experiment("pause-gated")
        assert experiment.feature_flag.active is True
        self._create_disable_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().pause_experiment(experiment, request=self._request())

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is True

    def test_resume_under_enable_policy_requires_approval(self, _mock_enabled):
        experiment = self._create_launched_experiment("resume-gated")
        # Pause it first (no policy yet) so it's genuinely paused.
        self._service().pause_experiment(experiment, request=self._request())
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False

        self._create_enable_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().resume_experiment(experiment, request=self._request())

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False

    def test_launch_without_policy_flips_flag_and_sets_start_date(self, _mock_enabled):
        experiment = self._create_draft_experiment("launch-ungated")

        launched = self._service().launch_experiment(experiment, request=self._request())

        assert launched.start_date is not None
        launched.feature_flag.refresh_from_db()
        assert launched.feature_flag.active is True

    def test_ship_variant_under_update_policy_requires_approval(self, _mock_enabled):
        # ship_variant rewrites the flag's variant rollout (50/50 -> 100/0), a rollout_percentage
        # change gated by feature_flag.update. It routes through FeatureFlagSerializer, so the gate
        # must fire and leave the flag's filters untouched.
        experiment = self._create_launched_experiment("ship-gated")
        original_filters = experiment.feature_flag.filters
        original_variants = original_filters["multivariate"]["variants"]
        assert any(v["key"] == "test" and v["rollout_percentage"] == 50 for v in original_variants)

        self._create_update_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().ship_variant(experiment, variant_key="test", request=self._request())

        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        # Flag distribution unchanged and experiment not ended.
        assert experiment.feature_flag.filters["multivariate"]["variants"] == original_variants
        assert experiment.end_date is None

    def test_update_experiment_variant_edit_under_update_policy_leaves_pending_cr(self, _mock_enabled):
        # update_experiment() syncs a variant/rollout change back through FeatureFlagSerializer,
        # gated by feature_flag.update. The gated flag write runs OUTSIDE the method's atomic block
        # (like ship_variant/launch/pause/resume), so ApprovalRequired leaves the flag untouched
        # AND the pending ChangeRequest survives for an approver to act on — it is not rolled back.
        experiment = self._create_launched_experiment("update-gated")
        original_variants = experiment.feature_flag.filters["multivariate"]["variants"]
        self._create_update_policy()

        new_variants = [
            {"key": "control", "rollout_percentage": 10},
            {"key": "test", "rollout_percentage": 90},
        ]
        context = {
            "request": self._request(),
            "team_id": self.team.id,
            "project_id": self.team.project_id,
            "get_team": lambda: self.team,
            "get_organization": lambda: self.organization,
        }

        with self.assertRaises(ApprovalRequired):
            self._service().update_experiment(
                experiment,
                {"update_feature_flag_params": True},
                feature_flag_config={"filters": {"multivariate": {"variants": new_variants}}},
                serializer_context=context,
            )

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters["multivariate"]["variants"] == original_variants
        assert ChangeRequest.objects.filter(state=ChangeRequestState.PENDING).count() == 1
        assert ChangeRequest.objects.filter(state=ChangeRequestState.APPLIED).count() == 0

    def test_update_experiment_invalid_payload_does_not_commit_flag_variant_change(self, _mock_enabled):
        # A single update that both rewrites the flag's variant rollout (update_feature_flag_params=True)
        # and carries an invalid stats_config must fail closed WITHOUT committing the flag change. The flag
        # write autocommits (no ATOMIC_REQUESTS), so the payload validation has to run before it — otherwise
        # a 400 would leave the flag rewritten while the experiment stays untouched (flag/experiment drift).
        # No policy here: without the pre-flag validation the flag write would succeed and commit.
        experiment = self._create_launched_experiment("update-invalid-payload")
        original_variants = experiment.feature_flag.filters["multivariate"]["variants"]

        new_variants = [
            {"key": "control", "rollout_percentage": 10},
            {"key": "test", "rollout_percentage": 90},
        ]
        context = {
            "request": self._request(),
            "team_id": self.team.id,
            "project_id": self.team.project_id,
            "get_team": lambda: self.team,
            "get_organization": lambda: self.organization,
        }

        with self.assertRaises(ValidationError):
            self._service().update_experiment(
                experiment,
                {
                    "update_feature_flag_params": True,
                    # baseline_variant_key references a variant that does not exist in the resolved set.
                    "stats_config": {"baseline_variant_key": "nonexistent"},
                },
                feature_flag_config={"filters": {"multivariate": {"variants": new_variants}}},
                serializer_context=context,
            )

        experiment.feature_flag.refresh_from_db()
        # The invalid payload must not have committed the flag's variant rewrite.
        assert experiment.feature_flag.filters["multivariate"]["variants"] == original_variants
