"""Approval actions for the experiment operations that rewrite who an experiment reaches.

Freezing exposure, unfreezing it and resetting an experiment each rewrite the release conditions of
the experiment's flag. Gating that flag write would review a freeze whose snapshot was built when
the request was made, so users who enrolled before approval would lose their variant, and a
rejected request would leave the snapshot cohort behind. So each operation is gated as a whole at
its endpoint, and an approved request runs the operation itself, at approval.

They have no policy of their own. They borrow `experiment.update`, which reviews the other changes
to who an experiment reaches, and only when that policy reviews every change or any change to the
release conditions: its other conditions name the rollout, which these operations never change.

A `PATCH` that clears a launched experiment's start date is held as a reset too, and an approved
request replays that same update.

The actions live here rather than in approvals, because applying one runs the experiment service and
approvals may not import this product. The app config registers them with approvals at startup.
"""

from collections.abc import Mapping
from typing import Any, Optional

from rest_framework.exceptions import APIException, ValidationError

from products.approvals.backend.actions.base import BaseAction
from products.approvals.backend.exceptions import ApplyFailed, PreconditionFailed
from products.approvals.backend.ownership import scope_by_owner_enabled
from products.experiments.backend.models.experiment import (
    EXPOSURE_FROZEN_GROUP_KEY,
    Experiment,
    experiment_has_legacy_metrics,
)

_STATUS_TEXT = {
    "draft": "a draft",
    "running": "running",
    "paused": "paused",
    "exposure_frozen": "frozen",
    "stopped": "ended",
}


def _isoformat_or_none(value: Any) -> Optional[str]:
    return value.isoformat() if value else None


def _run_marker(experiment: Experiment) -> dict[str, Optional[str]]:
    """The dates that tell runs apart: a reset clears them, a relaunch sets a new start, and an end sets the end."""
    return {
        "run_started_at": _isoformat_or_none(experiment.start_date),
        "run_ended_at": _isoformat_or_none(experiment.end_date),
    }


def _status_text(experiment: Experiment) -> str:
    return _STATUS_TEXT.get(experiment.status_label, experiment.status_label)


def _flag_has_freeze_stamp(experiment: Experiment) -> bool:
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if feature_flag_id is None:
        return False
    groups = (experiment.feature_flag.filters or {}).get("groups") or []
    return any(isinstance(group, dict) and group.get(EXPOSURE_FROZEN_GROUP_KEY) is True for group in groups)


def _clears_start_date(request) -> bool:
    data = getattr(request, "data", None)
    return isinstance(data, Mapping) and "start_date" in data and data["start_date"] is None


def _validation_message(error: ValidationError) -> str:
    """Join the messages of a validation error into plain text for the change request."""
    detail = error.detail
    values = detail.values() if isinstance(detail, dict) else detail
    return " ".join(str(message) for value in values for message in (value if isinstance(value, list) else [value]))


class ExperimentLifecycleActionBase(BaseAction):
    """Gate an experiment operation at its endpoint and run it when the request is approved."""

    version = 1
    resource_type = "experiment"
    fallback_policy_action_keys = ("experiment.update",)
    fallback_policy_must_be_unconditioned = True
    fallback_policy_gated_fields = ("release_conditions",)
    accepts_own_policy = False

    # The `ExperimentService` method that runs the operation.
    operation: str
    # The `ExperimentService` method that runs the operation's checks without running it.
    request_check: str
    target_status: str
    already_done_message: str

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
            **_run_marker(experiment),
            "current_state": {"status": experiment.status_label},
            "gated_changes": {"status": cls.target_status},
        }

    @classmethod
    def refuse_change_request(cls, request, intent_data: dict[str, Any]) -> Optional[APIException]:
        """Refuse a request that could only fail at approval, with the error the operation gives now."""
        # Deferred for the same reason as in `apply`.
        from products.experiments.backend.experiment_service import ExperimentService  # noqa: PLC0415

        experiment_id = intent_data.get("experiment_id")
        experiment = (
            Experiment.objects.select_related("team", "feature_flag").filter(id=experiment_id, deleted=False).first()
            if isinstance(experiment_id, int)
            else None
        )
        if experiment is None:
            return None
        try:
            getattr(ExperimentService(team=experiment.team, user=request.user), cls.request_check)(experiment)
        except APIException as error:
            return error
        return None

    @classmethod
    def get_duplicate_filter(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        # A request made for an earlier run can never apply, so it must not block a request for this run.
        return {f"intent__{key}": intent_data.get(key) for key in ("run_started_at", "run_ended_at")}

    @classmethod
    def prepare_context(cls, change_request, base_context: dict[str, Any]) -> dict[str, Any]:
        context = dict(base_context)
        # A deleted experiment's flag can still serve, so an approved operation must not rewrite it.
        context["instance"] = Experiment.objects.filter(
            team_id=change_request.team_id, id=change_request.intent.get("experiment_id"), deleted=False
        ).first()
        return context

    @classmethod
    def _run_change_message(cls, intent_data: dict[str, Any], experiment: Experiment) -> Optional[str]:
        """Why the approvers reviewed another run of the experiment, or None when the run is the same."""
        marker = _run_marker(experiment)
        if intent_data.get("run_started_at") != marker["run_started_at"]:
            return "The experiment was reset or relaunched, or its start date changed, after this request was created"
        if intent_data.get("run_ended_at") != marker["run_ended_at"]:
            return "The experiment was ended, or its end date changed, after this request was created"
        return None

    @classmethod
    def check_staleness(cls, intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None) -> bool:
        experiment = context.get("instance") if context else None
        return (
            experiment is None
            or cls._run_change_message(intent_data, experiment) is not None
            or not cls.can_run(experiment)
        )

    @classmethod
    def validate_intent(
        cls, intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        # The intent names an operation, not a payload, so there is nothing to re-validate.
        return True, None

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user, context: Optional[dict[str, Any]] = None) -> Any:
        experiment = context.get("instance") if context else None
        if experiment is None:
            raise PreconditionFailed("The experiment no longer exists")
        if cls.has_run(experiment):
            raise PreconditionFailed(cls.already_done_message)
        run_change = cls._run_change_message(validated_intent, experiment)
        if run_change is not None:
            raise PreconditionFailed(run_change)
        if not cls.can_run(experiment):
            raise PreconditionFailed(f"This can't run while the experiment is {_status_text(experiment)}")

        try:
            return cls._run(experiment, validated_intent, user)
        except ValidationError as e:
            raise ApplyFailed(f"{cls.description} failed: {_validation_message(e)}")

    @classmethod
    def _run(cls, experiment: Experiment, validated_intent: dict[str, Any], user) -> Any:
        # Deferred: the app config imports this module at startup, and the service pulls in most of
        # the experiments product, which a process that never applies a request does not need.
        from posthog.api.utils import ServiceRequest  # noqa: PLC0415

        from products.experiments.backend.experiment_service import ExperimentService  # noqa: PLC0415

        service = ExperimentService(team=experiment.team, user=user)
        return getattr(service, cls.operation)(experiment, request=ServiceRequest(user, method="POST"))

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
    request_check = "check_freeze_exposure"
    target_status = "exposure_frozen"
    already_done_message = "The experiment's exposure is already frozen"

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
    request_check = "check_unfreeze_exposure"
    target_status = "running"
    already_done_message = "The experiment's exposure is no longer frozen"

    @classmethod
    def can_run(cls, experiment: Experiment) -> bool:
        return experiment.is_exposure_frozen

    @classmethod
    def has_run(cls, experiment: Experiment) -> bool:
        # `is_exposure_frozen` reads a paused experiment, and a flag with a new unstamped group, as
        # unfrozen, but both keep the narrowing on the stamped groups.
        return experiment.is_running and not _flag_has_freeze_stamp(experiment)

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        name = intent_data.get("experiment_name", "unknown")
        return cls._display(intent_data, f"Unfreeze exposure of experiment '{name}': new users can enroll again")


class ResetExperimentAction(ExperimentLifecycleActionBase):
    """Gate resetting an experiment to a draft, through its endpoint or an update that clears its start date."""

    key = "experiment.reset"
    description = "Reset an experiment to a draft"
    operation = "reset_experiment"
    request_check = "check_reset_experiment"
    target_status = "draft"
    already_done_message = "The experiment is already a draft"

    @classmethod
    def can_run(cls, experiment: Experiment) -> bool:
        return not experiment.is_draft

    @classmethod
    def has_run(cls, experiment: Experiment) -> bool:
        return experiment.is_draft

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        if getattr(view, "action", None) in ("update", "partial_update"):
            if not _clears_start_date(request):
                return False
            experiment = cls._get_instance(view, *args, **kwargs)
            # The update refuses a start date change on an experiment with legacy metrics, as it always did.
            if isinstance(experiment, Experiment) and experiment_has_legacy_metrics(experiment):
                return False
        return super().detect(request, view, *args, **kwargs)

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        intent = super().extract_intent(request, view, *args, **kwargs)
        if getattr(view, "action", None) in ("update", "partial_update"):
            intent["update_payload"] = {key: request.data[key] for key in request.data}
            intent["update_partial"] = view.action == "partial_update"
            intent["gated_changes"] = intent["update_payload"]
        else:
            experiment = cls._get_instance(view, *args, **kwargs)
            intent["removes_exposure_freeze"] = _flag_has_freeze_stamp(experiment)
        return intent

    @classmethod
    def refuse_change_request(cls, request, intent_data: dict[str, Any]) -> Optional[APIException]:
        if "update_payload" in intent_data:
            # The update runs its own checks, and `validate_intent` runs them for the request.
            return None
        return super().refuse_change_request(request, intent_data)

    @classmethod
    def validate_intent(
        cls, intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        payload = intent_data.get("update_payload")
        view = context.get("view") if context else None
        if payload is None or view is None:
            return True, None
        # The update would refuse an invalid payload at once, so the request is refused the same way.
        serializer = view.get_serializer(
            view.get_object(), data=payload, partial=intent_data.get("update_partial", True)
        )
        if serializer.is_valid():
            return True, None
        return False, serializer.errors

    @classmethod
    def _run(cls, experiment: Experiment, validated_intent: dict[str, Any], user) -> Any:
        payload = validated_intent.get("update_payload")
        if payload is None:
            return super()._run(experiment, validated_intent, user)
        return cls._replay_update(experiment, payload, partial=validated_intent.get("update_partial", True), user=user)

    @classmethod
    def _replay_update(cls, experiment: Experiment, payload: dict[str, Any], *, partial: bool, user) -> Experiment:
        """Run the held update unchanged, through the serializer the endpoint uses."""
        # Deferred for the same reason as in `_run`, and the serializer pulls in the API layer too.
        from posthog.api.utils import ServiceRequest  # noqa: PLC0415

        from products.experiments.backend.presentation.serializers import ExperimentSerializer  # noqa: PLC0415

        request = ServiceRequest(user, method="PATCH" if partial else "PUT")
        request.data = payload
        serializer = ExperimentSerializer(
            experiment,
            data=payload,
            partial=partial,
            context={
                "request": request,
                "team_id": experiment.team_id,
                "project_id": experiment.team.project_id,
                "get_team": lambda: experiment.team,
            },
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        name = intent_data.get("experiment_name", "unknown")
        if "update_payload" in intent_data:
            description = f"Update experiment '{name}' and clear its start date"
        elif intent_data.get("removes_exposure_freeze"):
            description = (
                f"Reset experiment '{name}' to a draft. This also removes its exposure freeze, "
                "so new users can enroll again, and deletes the snapshot cohort"
            )
        else:
            description = f"Reset experiment '{name}' to a draft"
        return cls._display(intent_data, description)


LIFECYCLE_ACTIONS: tuple[type[ExperimentLifecycleActionBase], ...] = (
    FreezeExposureAction,
    UnfreezeExposureAction,
    ResetExperimentAction,
)
