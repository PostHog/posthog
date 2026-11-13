"""Actions that make a new experiment from an existing one: duplicate, copy to another project and migrate."""

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import get_authenticator_scoped_team_ids, is_scout_sandbox_request
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade.contracts import LegacyMigrationError
from products.experiments.backend.facade.legacy_migration import migrate_experiment as migrate_legacy_experiment
from products.experiments.backend.models.experiment import Experiment, experiment_has_legacy_metrics
from products.experiments.backend.presentation.scout_writes import (
    refuse_scout_experiment_copy_to_project,
    refuse_scout_experiment_migrate,
)
from products.experiments.backend.presentation.serializers.experiment_crud import ExperimentSerializer
from products.experiments.backend.presentation.serializers.lifecycle import CopyExperimentToProjectSerializer


class ExperimentCopiesMixin(TeamAndOrgViewSetMixin):
    def _check_copy_target_access(self, request: Request, target_team: Team) -> None:
        """Authorize the target project of a cross-project copy.

        Every class in the permission stack resolves against `view.team`, which is the source
        project in the URL, so the target project is not checked at all by the time the action
        body runs. This applies the same gates the target project's own `POST /experiments/`
        would apply: the credential's project scope, project membership, and experiment editor
        access in the target.
        """
        scoped_teams = get_authenticator_scoped_team_ids(getattr(request, "successful_authenticator", None))
        if scoped_teams is not None and target_team.id not in scoped_teams:
            raise PermissionDenied(f"API key does not have access to the requested project: ID {target_team.id}.")

        user = cast(User, request.user)
        effective_level = UserPermissions(user=user).team(target_team).effective_membership_level
        if effective_level is None or effective_level < OrganizationMembership.Level.MEMBER:
            raise PermissionDenied("You do not have write access to the target project.")

        target_access_control = UserAccessControl(user=user, team=target_team)
        if not target_access_control.check_access_level_for_object(
            target_team, required_level="member"
        ) or not target_access_control.check_access_level_for_resource("experiment", required_level="editor"):
            raise PermissionDenied("You do not have permission to create experiments in the target project.")

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def duplicate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source_experiment: Experiment = self.get_object()

        if experiment_has_legacy_metrics(source_experiment):
            return Response(
                {"detail": "Duplication is not supported for experiments using legacy metrics."},
                status=400,
            )

        feature_flag_key = request.data.get("feature_flag_key")
        name = request.data.get("name")

        service = ExperimentService(team=self.team, user=request.user)
        duplicate_experiment = service.duplicate_experiment(
            source_experiment,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context=self.get_serializer_context(),
        )

        return Response(
            ExperimentSerializer(duplicate_experiment, context=self.get_serializer_context()).data, status=201
        )

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def migrate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Move a legacy experiment onto the new experiments engine.

        Creates a new experiment with the same configuration and its metrics converted
        to the new format, and returns it. Legacy experiments no longer show results,
        so this is how to get results for one. The legacy experiment is left untouched,
        so the project ends up with two experiments. Both point at the same feature
        flag, so no new rollout is needed and users keep the variant they already have.

        Legacy shared metrics used by the experiment are converted as part of the same
        call. Each one gets a new shared metric, and the new experiment links to that.

        Calling this again returns the experiment created the first time instead of
        making another copy.

        Returns 400 if the experiment already uses the new engine.
        """
        refuse_scout_experiment_migrate(is_scout_sandbox_request(request))
        experiment: Experiment = self.get_object()

        if not experiment_has_legacy_metrics(experiment):
            raise ValidationError(
                "This experiment already uses the new experiments engine, so there is nothing to migrate."
            )

        try:
            migration = migrate_legacy_experiment(experiment.id, self.team.id, migrate_shared_metrics=True)
        except (LegacyMigrationError, ValueError) as e:
            raise ValidationError(f"Couldn't migrate this experiment: {e}. Contact support if it keeps happening.")

        return Response(ExperimentSerializer(migration.experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=CopyExperimentToProjectSerializer,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, url_path="copy_to_project", required_scopes=["experiment:write"])
    def copy_to_project(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Copy an experiment into another project in the same organization as a new draft."""
        refuse_scout_experiment_copy_to_project(is_scout_sandbox_request(request))
        source_experiment: Experiment = self.get_object()

        if experiment_has_legacy_metrics(source_experiment):
            return Response(
                {"detail": "Copying is not supported for experiments using legacy metrics."},
                status=400,
            )

        request_serializer = CopyExperimentToProjectSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        target_team_id = request_serializer.validated_data["target_team_id"]
        target_team = Team.objects.filter(id=target_team_id, organization_id=self.team.organization_id).first()
        if target_team is None:
            return Response({"detail": "Target team not found."}, status=404)

        self._check_copy_target_access(request, target_team)

        feature_flag_key = request_serializer.validated_data.get("feature_flag_key")
        name = request_serializer.validated_data.get("name")

        service = ExperimentService(team=self.team, user=request.user)
        new_experiment = service.copy_experiment_to_project(
            source_experiment,
            target_team,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context={
                "request": request,
                "team_id": target_team.id,
                "project_id": target_team.project_id,
                "get_team": lambda: target_team,
            },
        )

        target_context = {
            **self.get_serializer_context(),
            "team_id": target_team.id,
            "project_id": target_team.project_id,
            "get_team": lambda: target_team,
        }
        return Response(ExperimentSerializer(new_experiment, context=target_context).data, status=201)
