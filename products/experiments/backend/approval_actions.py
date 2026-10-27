"""Approval actions for the experiment operations that rewrite who an experiment reaches.

Freezing exposure, unfreezing it and resetting an experiment each rewrite the release conditions of
the experiment's flag. Gating that flag write would review a freeze whose snapshot was built when
the request was made, so users who enrolled before approval would lose their variant, and a
rejected request would leave the snapshot cohort behind. So each operation is gated as a whole at
its endpoint, and an approved request runs the operation itself, at approval.

They have no policy of their own. They borrow `experiment.update`, which reviews the other changes
to who an experiment reaches, and only when that policy has no conditions: its conditions name the
rollout, which these operations never change.

The actions live here rather than in approvals, because applying one runs the experiment service and
approvals may not import this product. The app config registers them with approvals at startup.
"""

from typing import Any, Optional

from rest_framework.exceptions import ValidationError

from products.approvals.backend.actions.base import BaseAction
from products.approvals.backend.exceptions import ApplyFailed, PreconditionFailed
from products.approvals.backend.ownership import scope_by_owner_enabled
from products.experiments.backend.models.experiment import Experiment


class ExperimentLifecycleActionBase(BaseAction):
    """Gate an experiment operation at its endpoint and run it when the request is approved."""

    version = 1
    resource_type = "experiment"
    fallback_policy_action_keys = ("experiment.update",)
    fallback_policy_must_be_unconditioned = True

    # The `ExperimentService` method that runs the operation.
    operation: str

    @classmethod
    def can_run(cls, experiment: Experiment) -> bool:
        """Whether the operation would run on the experiment in its current state."""
        raise NotImplementedError

    @classmethod
    def has_run(cls, experiment: Experiment) -> bool:
        """Whether the experiment is already in the state the operation leads to."""
        raise NotImplementedError

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        organization = cls._get_organization(view)
        if organization is None or not scope_by_owner_enabled(organization):
            # Before the organization scopes policies by flag owner, its experiment policies are
            # unenforced copies, and these operations stay ungated as they always were.
            return False
        experiment = cls._get_instance(view, *args, **kwargs)
        # An operation the experiment cannot run fails with its own error. A change request for it
        # would ask approvers to review something that cannot happen.
        return isinstance(experiment, Experiment) and cls.can_run(experiment)

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        experiment = cls._get_instance(view, *args, **kwargs)
        return {
            "experiment_id": experiment.id,
            "experiment_name": experiment.name,
            "flag_key": experiment.feature_flag.key if experiment.feature_flag_id else None,
            "current_state": {"status": experiment.status_label},
            "gated_changes": {"operation": cls.operation},
        }

    @classmethod
    def get_target_filter(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        # The operations are POSTs, so the request carries no resource id. Match on the experiment.
        return {"intent__experiment_id": intent_data["experiment_id"]}

    @classmethod
    def prepare_context(cls, change_request, base_context: dict[str, Any]) -> dict[str, Any]:
        context = dict(base_context)
        context["instance"] = Experiment.objects.filter(
            team_id=change_request.team_id, id=change_request.intent.get("experiment_id")
        ).first()
        return context

    @classmethod
    def check_staleness(cls, intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None) -> bool:
        experiment = context.get("instance") if context else None
        return experiment is None or not cls.can_run(experiment)

    @classmethod
    def validate_intent(
        cls, intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        # The intent names an operation, not a payload, so there is nothing to re-validate.
        return True, None

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user, context: Optional[dict[str, Any]] = None) -> Any:
        # Deferred: the app config imports this module at startup, and the service pulls in most of
        # the experiments product, which a process that never applies a request does not need.
        from posthog.api.utils import ServiceRequest  # noqa: PLC0415

        from products.experiments.backend.experiment_service import ExperimentService  # noqa: PLC0415

        experiment = context.get("instance") if context else None
        if experiment is None:
            raise PreconditionFailed("The experiment no longer exists")
        if cls.has_run(experiment):
            return experiment
        if not cls.can_run(experiment):
            raise PreconditionFailed("The experiment changed after this request was created")

        service = ExperimentService(team=experiment.team, user=user)
        try:
            return getattr(service, cls.operation)(experiment, request=ServiceRequest(user, method="POST"))
        except ValidationError as e:
            raise ApplyFailed(f"{cls.description} failed: {e.detail}")

    @classmethod
    def _display(cls, intent_data: dict[str, Any], description: str) -> dict[str, Any]:
        return {
            "description": description,
            "before": intent_data.get("current_state", {}),
            "after": intent_data.get("gated_changes", {}),
        }


class FreezeExposureAction(ExperimentLifecycleActionBase):
    """Gate freezing an experiment's exposure, which stops new users from enrolling."""

    key = "experiment.freeze_exposure"
    description = "Freeze an experiment's exposure"
    operation = "freeze_exposure"

    @classmethod
    def can_run(cls, experiment: Experiment) -> bool:
        return experiment.can_freeze_exposure

    @classmethod
    def has_run(cls, experiment: Experiment) -> bool:
        return experiment.is_exposure_frozen

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        name = intent_data.get("experiment_name", "unknown")
        return cls._display(
            intent_data,
            f"Freeze exposure of experiment '{name}': enrolled users keep their variant, and nobody new enrolls",
        )


class UnfreezeExposureAction(ExperimentLifecycleActionBase):
    """Gate unfreezing an experiment's exposure, which lets new users enroll again."""

    key = "experiment.unfreeze_exposure"
    description = "Unfreeze an experiment's exposure"
    operation = "unfreeze_exposure"

    @classmethod
    def can_run(cls, experiment: Experiment) -> bool:
        return experiment.is_exposure_frozen

    @classmethod
    def has_run(cls, experiment: Experiment) -> bool:
        return experiment.is_running and not experiment.is_exposure_frozen

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        name = intent_data.get("experiment_name", "unknown")
        return cls._display(intent_data, f"Unfreeze exposure of experiment '{name}': new users can enroll again")


class ResetExperimentAction(ExperimentLifecycleActionBase):
    """Gate resetting an experiment to a draft, which also removes a frozen exposure."""

    key = "experiment.reset"
    description = "Reset an experiment to a draft"
    operation = "reset_experiment"

    @classmethod
    def can_run(cls, experiment: Experiment) -> bool:
        return not experiment.is_draft

    @classmethod
    def has_run(cls, experiment: Experiment) -> bool:
        return experiment.is_draft

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        name = intent_data.get("experiment_name", "unknown")
        return cls._display(intent_data, f"Reset experiment '{name}' to a draft")


LIFECYCLE_ACTIONS: tuple[type[ExperimentLifecycleActionBase], ...] = (
    FreezeExposureAction,
    UnfreezeExposureAction,
    ResetExperimentAction,
)
