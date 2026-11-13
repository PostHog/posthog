"""Lifecycle actions of an experiment: launch, pause, resume, freeze exposure, end, ship, archive, reset and flag cleanup."""

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import get_authenticator_scopes, is_scout_sandbox_request
from posthog.user_permissions import UserPermissions

from products.experiments.backend.experiment_service import ExperimentService

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.presentation.scout_writes import (
    refuse_scout_cleanup_pr,
    refuse_scout_ship_variant_without_flag_write,
)
from products.experiments.backend.presentation.serializers.experiment_crud import ExperimentSerializer
from products.experiments.backend.presentation.serializers.lifecycle import (
    ArchiveExperimentSerializer,
    EndExperimentSerializer,
    ExperimentFlagCleanupTargetSerializer,
    ExperimentFlagCleanupTaskSerializer,
    ShipVariantSerializer,
)
from products.tasks.backend.facade import api as tasks_facade


class ExperimentLifecycleMixin(TeamAndOrgViewSetMixin):
    def _check_team_default_repository_access(self, request: Request) -> None:
        """The team default cleanup repository is environment-wide configuration; writing it via
        experiments_config requires project admin (TeamMemberStrictManagementPermission), so the
        write through end/ship_variant must hold the same bar."""
        user_permissions = UserPermissions(user=cast(User, request.user))
        effective_level = user_permissions.team(self.team).effective_membership_level
        if effective_level is None or effective_level < OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("Setting the default cleanup repository requires project admin access.")

    def _token_can_write_feature_flag(self, request: Request) -> bool:
        """Whether the request's token carries feature_flag:write.

        Archiving/unarchiving an experiment can touch the linked flag's archived/active
        state as a side effect; that is a feature_flag write and must not be reachable with
        only experiment:write. Session and other non-token auth aren't scope-limited (gated by
        access control instead), mirroring APIScopePermission.
        """
        scopes = get_authenticator_scopes(request.successful_authenticator)
        if scopes is None:
            return True
        return "*" in scopes or "feature_flag:write" in scopes

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def launch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Launch a draft experiment.

        Validates the experiment is in draft state, activates its linked feature flag,
        sets start_date to the current server time, and transitions the experiment to running.
        Returns 400 if the experiment has already been launched or if the feature flag
        configuration is invalid (e.g. fewer than 2 variants).
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        launched_experiment = service.launch_experiment(experiment, request=request)
        return Response(ExperimentSerializer(launched_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=ArchiveExperimentSerializer,
        responses=ExperimentSerializer,
    )
    # required_scopes is computed by dangerously_get_required_scopes — disabling the linked
    # flag additionally requires feature_flag:write.
    @action(methods=["POST"], detail=True)
    def archive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Archive an ended experiment.

        Hides the experiment from the default list view. The experiment can be
        restored at any time by updating archived=false. When the linked feature
        flag is still enabled, pass disable_feature_flag=true to also disable and
        archive it. Returns 400 if the experiment is already archived or has not
        ended yet.
        """
        experiment: Experiment = self.get_object()
        request_serializer = ArchiveExperimentSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        service = ExperimentService(team=self.team, user=request.user)
        archived_experiment = service.archive_experiment(
            experiment,
            disable_feature_flag=request_serializer.validated_data["disable_feature_flag"],
            can_write_feature_flag=self._token_can_write_feature_flag(request),
            request=request,
        )
        return Response(ExperimentSerializer(archived_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def unarchive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Unarchive an archived experiment.

        Restores the experiment to the default list view. Returns 400 if the
        experiment is not currently archived.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        unarchived_experiment = service.unarchive_experiment(
            experiment,
            can_write_feature_flag=self._token_can_write_feature_flag(request),
            request=request,
        )
        return Response(ExperimentSerializer(unarchived_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=EndExperimentSerializer,
        responses=ExperimentSerializer,
    )
    # required_scopes is computed by dangerously_get_required_scopes; opening a cleanup PR
    # additionally requires task:write.
    @action(methods=["POST"], detail=True)
    def end(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        End a running experiment without shipping a variant.

        Sets end_date to now and marks the experiment as stopped. The feature
        flag is NOT modified — users continue to see their assigned variants
        and exposure events ($feature_flag_called) continue to be recorded.
        However, only data up to end_date is included in experiment results.

        Use this when:

        - You want to freeze the results window without changing which variant
          users see.
        - A variant was already shipped manually via the feature flag UI and
          the experiment just needs to be marked complete.

        The end_date can be adjusted after ending via PATCH if it needs to be
        backdated (e.g. to match when the flag was actually paused).

        Other options:
        - Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
        - Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).

        Returns 400 if the experiment is not running.
        """
        experiment: Experiment = self.get_object()
        request_serializer = EndExperimentSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        refuse_scout_cleanup_pr(
            is_scout_sandbox_request(request), open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"]
        )
        if request_serializer.validated_data["set_repository_as_team_default"]:
            self._check_team_default_repository_access(request)
        service = ExperimentService(team=self.team, user=request.user)
        ended_experiment = service.end_experiment(
            experiment,
            conclusion=request_serializer.validated_data.get("conclusion"),
            conclusion_comment=request_serializer.validated_data.get("conclusion_comment"),
            open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"],
            repository=request_serializer.validated_data.get("repository"),
            set_repository_as_team_default=request_serializer.validated_data["set_repository_as_team_default"],
            request=request,
        )
        return Response(ExperimentSerializer(ended_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=ShipVariantSerializer,
        responses=ExperimentSerializer,
    )
    # required_scopes is computed by dangerously_get_required_scopes; opening a cleanup PR
    # additionally requires task:write.
    @action(methods=["POST"], detail=True, url_path="ship_variant")
    def ship_variant(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Ship a variant and (optionally) end the experiment.

        Updates the feature flag so the selected variant gets 100% of the variant
        distribution. By default, existing release conditions on the flag are preserved
        untouched — the variant is served only to users who already match them. Pass
        ``release_to_everyone: true`` to also prepend a catch-all release condition
        that rolls the variant out to 100% of users (overrides any existing release
        conditions on the flag).

        Can be called on both running and stopped experiments. If the experiment is
        still running, it will also be ended (end_date set and status marked as stopped).
        If the experiment has already ended, only the flag is rewritten - this supports
        the "end first, ship later" workflow.

        If an approval policy requires review before changes on the flag take effect,
        the API returns 409 with a change_request_id. The experiment is NOT ended until
        the change request is approved and the user retries.

        Returns 400 if the experiment is in draft state, the variant_key is not found
        on the flag, or the experiment has no linked feature flag.
        """
        refuse_scout_ship_variant_without_flag_write(
            is_scout_sandbox_request(request), can_write_feature_flag=self._token_can_write_feature_flag(request)
        )
        experiment: Experiment = self.get_object()
        request_serializer = ShipVariantSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        refuse_scout_cleanup_pr(
            is_scout_sandbox_request(request), open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"]
        )
        if request_serializer.validated_data["set_repository_as_team_default"]:
            self._check_team_default_repository_access(request)
        service = ExperimentService(team=self.team, user=request.user)
        shipped_experiment = service.ship_variant(
            experiment,
            variant_key=request_serializer.validated_data["variant_key"],
            release_to_everyone=request_serializer.validated_data["release_to_everyone"],
            conclusion=request_serializer.validated_data.get("conclusion"),
            conclusion_comment=request_serializer.validated_data.get("conclusion_comment"),
            open_cleanup_pr=request_serializer.validated_data["open_cleanup_pr"],
            repository=request_serializer.validated_data.get("repository"),
            set_repository_as_team_default=request_serializer.validated_data["set_repository_as_team_default"],
            request=request,
        )
        return Response(ExperimentSerializer(shipped_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentFlagCleanupTaskSerializer,
    )
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def flag_cleanup_task(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Status of the flag-cleanup Desktop task opened for this experiment.

        When an experiment was ended or shipped with open_cleanup_pr=true, a Desktop task
        removes the experiment's feature-flag code and opens a draft pull request. This
        returns that task's latest run status and the PR URL once one is opened. Poll
        until is_terminal is true. Returns 404 when no cleanup task was opened.
        """
        experiment: Experiment = self.get_object()
        if not experiment.flag_cleanup_task_id:
            raise NotFound("No flag cleanup task was opened for this experiment.")
        # Read through the facade rather than the tasks API: cleanup tasks are creator-visible
        # there, but their status should be visible to everyone who can see the experiment.
        run = tasks_facade.get_latest_run_by_task([experiment.flag_cleanup_task_id]).get(
            str(experiment.flag_cleanup_task_id)
        )
        # get_latest_run_by_task filters by task id only. After a project transfer the
        # experiment can point at a task in the old team — treat that run as absent rather
        # than leaking its status across teams.
        if run is not None and run.team_id != experiment.team_id:
            run = None
        # The PR URL comes from the task run's output blob — only pass it through when it
        # actually points at GitHub, since the frontend renders it as a GitHub link.
        pr_url = run.pr_url if run else None
        if pr_url and not pr_url.startswith("https://github.com/"):
            pr_url = None
        response_serializer = ExperimentFlagCleanupTaskSerializer(
            {
                "task_id": experiment.flag_cleanup_task_id,
                "run_status": run.status if run else "queued",
                "is_terminal": run.is_terminal if run else False,
                "pr_url": pr_url,
                # Whether the tasks API would let this user open the task page — cleanup
                # tasks are creator-visible there today, so hide the link from everyone else.
                "can_view_task": tasks_facade.task_visible(
                    experiment.flag_cleanup_task_id, self.team.pk, cast(User, request.user).id
                ),
            }
        )
        return Response(response_serializer.data)

    @extend_schema(
        request=None,
        responses=ExperimentFlagCleanupTargetSerializer,
    )
    @action(methods=["GET"], detail=True, url_path="flag_cleanup_target", required_scopes=["experiment:read"])
    def flag_cleanup_target(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Repository a flag-cleanup pull request for this experiment would be opened in.

        Resolution order: the experiment's saved repository, else the environment's default
        cleanup repository, else the team's only connected GitHub repository. When the team
        has several repositories and none is saved (source=ambiguous), pass one via
        `repository` on end/ship_variant.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        target = service.get_cleanup_repository_target(experiment)
        return Response(ExperimentFlagCleanupTargetSerializer(target).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def pause(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Pause a running experiment.

        Deactivates the linked feature flag so it is no longer returned by the
        /decide endpoint. Users fall back to the application default (typically
        the control experience), and no new exposure events are recorded (i.e.
        $feature_flag_called is not fired).
        Returns 400 if the experiment is not running or is already paused.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        paused_experiment = service.pause_experiment(experiment, request=request)
        return Response(ExperimentSerializer(paused_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def resume(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Resume a paused experiment.

        Reactivates the linked feature flag so it is returned by /decide again.
        Users are re-bucketed deterministically into the same variants they had
        before the pause, and exposure tracking resumes.
        Returns 400 if the experiment is not running or is not paused.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        resumed_experiment = service.resume_experiment(experiment, request=request)
        return Response(ExperimentSerializer(resumed_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def freeze_exposure(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Freeze exposure on a running experiment while metrics keep flowing.

        Snapshots the already-exposed users into a static cohort and narrows the
        linked feature flag so only those users keep matching — new users can no
        longer enter the experiment. ``end_date`` is left null so long-term metrics
        (revenue/LTV/renewals/retention) keep accumulating. Enrolled users keep
        their assigned variant. The serialized status becomes 'exposure_frozen'.

        Returns 400 if the experiment is not running, exposure is already frozen,
        the experiment is group-aggregated (group flags cannot be frozen with a
        person cohort), or the exposed set is too large to snapshot synchronously.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        frozen_experiment = service.freeze_exposure(experiment, request=request)
        return Response(ExperimentSerializer(frozen_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def unfreeze_exposure(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Reopen enrollment on an exposure-frozen experiment.

        Removes the snapshot-cohort condition and freeze markers from every release
        group, restoring the flag's original targeting: new users can enroll again
        and already-enrolled users keep their assigned variant. The snapshot cohort
        is soft-deleted. The serialized status returns to 'running'.

        Returns 400 if the experiment is not running or its exposure is not frozen.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        unfrozen_experiment = service.unfreeze_exposure(experiment, request=request)
        return Response(ExperimentSerializer(unfrozen_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def reset(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Reset an experiment back to draft state.

        Clears start/end dates, conclusion, archived flag, and any flag-cleanup
        task pointer. The feature flag is left unchanged — users continue to see
        their assigned variants.

        Previously collected events still exist but won't be included in
        results unless the start date is manually adjusted after re-launch.

        Returns 400 if the experiment is already in draft state.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        reset_experiment = service.reset_experiment(experiment, request=request)
        return Response(ExperimentSerializer(reset_experiment, context=self.get_serializer_context()).data)
