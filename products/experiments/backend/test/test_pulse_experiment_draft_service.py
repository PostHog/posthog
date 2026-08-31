import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import transaction

from rest_framework.exceptions import ValidationError

from posthog.models.user import User

from products.approvals.backend.exceptions import ApprovalRequired
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.experiments.backend.facade import (
    create_pulse_experiment_draft,
    create_pulse_experiment_draft_experiment,
    resolve_or_create_pulse_experiment_draft_flag,
)
from products.experiments.backend.facade.contracts import (
    PulseExperimentDraftInput,
    PulseExperimentMetricRef,
    PulseExperimentVariant,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestCreatePulseExperimentDraft(APIBaseTest):
    def _input(self) -> PulseExperimentDraftInput:
        return PulseExperimentDraftInput(
            name="Improve checkout completion",
            hypothesis="A shorter checkout will increase completed purchases.",
            description="Test a reduced checkout form.",
            target_description="Visitors who begin checkout.",
            variants=(
                PulseExperimentVariant(key="control", name="Current checkout"),
                PulseExperimentVariant(key="short-form", name="Short checkout"),
            ),
            primary_metric=PulseExperimentMetricRef(kind="event", event_name="purchase_completed"),
            secondary_metrics=(PulseExperimentMetricRef(kind="event", event_name="checkout_started"),),
        )

    def test_creates_a_new_inert_draft_and_preserves_metric_refs(self) -> None:
        EventDefinition.objects.create(team=self.team, name="purchase_completed")
        EventDefinition.objects.create(team=self.team, name="checkout_started")

        result = create_pulse_experiment_draft(
            team=self.team,
            user=self.user,
            feature_flag_key="pulse-exp-unique-key",
            input_dto=self._input(),
        )

        experiment = Experiment.objects.get(pk=result.id)
        flag = experiment.feature_flag

        assert experiment.is_draft
        assert experiment.start_date is None
        assert experiment.end_date is None
        assert experiment.scheduling_config is None
        assert experiment.holdout_id is None
        assert experiment.repository is None
        assert experiment.description == (
            "Test a reduced checkout form.\n\n"
            "Hypothesis: A shorter checkout will increase completed purchases.\n\n"
            "Target: Visitors who begin checkout."
        )
        assert flag.key == "pulse-exp-unique-key"
        assert flag.active is False
        assert flag.filters == {
            "aggregation_group_type_index": None,
            "groups": [{"properties": [], "rollout_percentage": 0, "aggregation_group_type_index": None}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Current checkout", "rollout_percentage": 50},
                    {"key": "short-form", "name": "Short checkout", "rollout_percentage": 50},
                ]
            },
        }
        assert experiment.metrics is not None
        assert experiment.metrics_secondary is not None
        assert experiment.metrics[0]["source"] == {"kind": "EventsNode", "event": "purchase_completed"}
        assert experiment.metrics_secondary[0]["source"] == {"kind": "EventsNode", "event": "checkout_started"}

    def test_phase_one_reconciles_only_the_exact_server_owned_flag(self) -> None:
        EventDefinition.objects.create(team=self.team, name="purchase_completed")
        EventDefinition.objects.create(team=self.team, name="checkout_started")

        created = resolve_or_create_pulse_experiment_draft_flag(
            team=self.team,
            user=self.user,
            feature_flag_key="pulse-exp-reconcile",
            input_dto=self._input(),
        )
        reconciled = resolve_or_create_pulse_experiment_draft_flag(
            team=self.team,
            user=self.user,
            feature_flag_key="pulse-exp-reconcile",
            input_dto=self._input(),
        )

        assert reconciled.id == created.id
        assert Experiment.objects.filter(feature_flag_id=created.id).exists() is False

        FeatureFlag.objects.filter(pk=created.id).update(active=True)

        with pytest.raises(ValidationError, match="different configuration"):
            resolve_or_create_pulse_experiment_draft_flag(
                team=self.team,
                user=self.user,
                feature_flag_key="pulse-exp-reconcile",
                input_dto=self._input(),
            )

        other_user = User.objects.create_and_join(self.organization, "other-owner@example.com", None)
        FeatureFlag.objects.filter(pk=created.id).update(active=False, created_by=other_user)

        with pytest.raises(ValidationError, match="different configuration"):
            resolve_or_create_pulse_experiment_draft_flag(
                team=self.team,
                user=self.user,
                feature_flag_key="pulse-exp-reconcile",
                input_dto=self._input(),
            )

    def test_phase_two_creates_the_experiment_inside_the_callers_transaction(self) -> None:
        EventDefinition.objects.create(team=self.team, name="purchase_completed")
        EventDefinition.objects.create(team=self.team, name="checkout_started")
        flag = resolve_or_create_pulse_experiment_draft_flag(
            team=self.team,
            user=self.user,
            feature_flag_key="pulse-exp-atomic",
            input_dto=self._input(),
        )

        with transaction.atomic():
            result = create_pulse_experiment_draft_experiment(
                team=self.team,
                user=self.user,
                feature_flag_id=flag.id,
                feature_flag_key=flag.key,
                input_dto=self._input(),
            )

        assert result.feature_flag_id == flag.id
        assert Experiment.objects.filter(pk=result.id, feature_flag_id=flag.id).exists()

    def test_phase_two_rolls_back_with_the_callers_artifact_transaction(self) -> None:
        EventDefinition.objects.create(team=self.team, name="purchase_completed")
        EventDefinition.objects.create(team=self.team, name="checkout_started")
        flag = resolve_or_create_pulse_experiment_draft_flag(
            team=self.team,
            user=self.user,
            feature_flag_key="pulse-exp-rollback",
            input_dto=self._input(),
        )

        with pytest.raises(RuntimeError, match="abort artifact finalization"):
            with transaction.atomic():
                create_pulse_experiment_draft_experiment(
                    team=self.team,
                    user=self.user,
                    feature_flag_id=flag.id,
                    feature_flag_key=flag.key,
                    input_dto=self._input(),
                )
                raise RuntimeError("abort artifact finalization")

        assert Experiment.objects.filter(feature_flag_id=flag.id).exists() is False

    def test_refuses_to_reuse_an_existing_feature_flag(self) -> None:
        EventDefinition.objects.create(team=self.team, name="purchase_completed")
        EventDefinition.objects.create(team=self.team, name="checkout_started")
        existing = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="pulse-exp-collision",
            name="Existing flag",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        with pytest.raises(ValidationError, match="different configuration"):
            create_pulse_experiment_draft(
                team=self.team,
                user=self.user,
                feature_flag_key=existing.key,
                input_dto=self._input(),
            )

        existing.refresh_from_db()
        assert existing.active is True
        assert Experiment.objects.filter(feature_flag=existing).exists() is False

    def test_refuses_to_reuse_a_soft_deleted_feature_flag(self) -> None:
        EventDefinition.objects.create(team=self.team, name="purchase_completed")
        EventDefinition.objects.create(team=self.team, name="checkout_started")
        existing = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="pulse-exp-deleted-collision",
            name="Deleted flag",
            active=False,
            deleted=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 0}]},
        )

        with pytest.raises(ValidationError, match="different configuration"):
            resolve_or_create_pulse_experiment_draft_flag(
                team=self.team,
                user=self.user,
                feature_flag_key=existing.key,
                input_dto=self._input(),
            )

        existing.refresh_from_db()
        assert existing.deleted is True

    def test_rejects_metric_references_that_do_not_belong_to_the_team(self) -> None:
        with pytest.raises(ValidationError, match="not found"):
            create_pulse_experiment_draft(
                team=self.team,
                user=self.user,
                feature_flag_key="pulse-exp-invalid-metric",
                input_dto=self._input(),
            )

        assert FeatureFlag.objects.filter(team=self.team, key="pulse-exp-invalid-metric").exists() is False

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_approval_required_does_not_create_an_experiment_or_lose_the_change_request(self, _mock_enabled) -> None:
        self.organization.available_product_features = [{"key": "approvals", "name": "approvals"}]
        self.organization.save()
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        EventDefinition.objects.create(team=self.team, name="purchase_completed")
        EventDefinition.objects.create(team=self.team, name="checkout_started")

        with pytest.raises(ApprovalRequired):
            create_pulse_experiment_draft(
                team=self.team,
                user=self.user,
                feature_flag_key="pulse-exp-needs-approval",
                input_dto=self._input(),
            )

        assert Experiment.objects.filter(team=self.team, name="Improve checkout completion").exists() is False
        assert ChangeRequest.objects.filter(state=ChangeRequestState.PENDING).count() == 1
