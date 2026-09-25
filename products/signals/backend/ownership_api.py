from __future__ import annotations

from typing import cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import User
from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.permissions import (
    APIScopePermission,
    TeamMemberLightManagementPermission,
    get_authenticator_scoped_team_ids,
)

from products.access_control.backend.facade.api import get_routing_roles
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import NoteArtefact, SuggestedReviewerEntry
from products.signals.backend.models import (
    SignalDomainPreference,
    SignalProductDomain,
    SignalReport,
    SignalReportArtefact,
    SignalReportRouting,
    SignalReviewerExclusion,
    SignalRoutingBatch,
    SignalRoutingBatchChange,
    SignalRoutingProposal,
)
from products.signals.backend.ownership import ReviewerRoutingPolicy, current_eligible_reviewers, remove_my_suggestion
from products.signals.backend.ownership_classification import record_routing_proposal
from products.signals.backend.ownership_preferences import DomainPreferenceService
from products.signals.backend.ownership_serializers import (
    SignalDomainPreferenceSerializer,
    SignalDomainPreferenceWriteSerializer,
    SignalDomainPreviewSerializer,
    SignalPersonalCorrectionSerializer,
    SignalProductDomainSerializer,
    SignalReportRoutingSerializer,
    SignalRoutingBatchReportSerializer,
    SignalRoutingBatchSerializer,
    SignalRoutingCorrectionSerializer,
    SignalRoutingProposalSerializer,
    SignalRoutingProposalWriteSerializer,
    SignalRoutingRoleSerializer,
    SignalRoutingSuggestionSerializer,
)
from products.signals.backend.ownership_suggestions import suggested_domain_preferences
from products.signals.backend.ownership_telemetry import capture_routing_change
from products.signals.backend.report_claims import get_active_claim, get_active_claims, responsible_user
from products.signals.backend.task_attribution import resolve_request_attribution


class _OwnershipViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, TeamMemberLightManagementPermission]
    scope_object = "task"
    requires_resource_level_access = True

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str]:
        return ["task:read"] if request.method in ("GET", "HEAD", "OPTIONS") else ["task:write"]

    def require_personal_action(self) -> User:
        if (
            is_impersonated_session(self.request)
            or resolve_request_attribution(self.request, self.team.id).kind != "user"
        ):
            raise PermissionDenied("Update personal routing from your own inbox.")
        return cast(User, self.request.user)


class SignalProductDomainViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    _OwnershipViewSet,
):
    serializer_class = SignalProductDomainSerializer
    queryset = SignalProductDomain.objects.unscoped().select_related("owning_role").order_by("name", "id")

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["team_id"] = self.team_id
        return context

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        try:
            with transaction.atomic():
                serializer.save(team_id=self.team.id)
        except IntegrityError as error:
            if getattr(getattr(error.__cause__, "diag", None), "constraint_name", None) == "signals_domain_team_name":
                raise serializers.ValidationError({"name": "This product domain already exists. Choose another name."})
            raise

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        assert serializer.instance is not None
        try:
            with transaction.atomic():
                domain = (
                    SignalProductDomain.objects.for_team(self.team.id)
                    .select_for_update()
                    .get(id=serializer.instance.id)
                )
                serializer.instance = domain
                serializer.save(revision=domain.revision + 1)
        except IntegrityError as error:
            if getattr(getattr(error.__cause__, "diag", None), "constraint_name", None) == "signals_domain_team_name":
                raise serializers.ValidationError({"name": "This product domain already exists. Choose another name."})
            raise

    @extend_schema(responses=SignalRoutingRoleSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def teams(self, request: Request, **kwargs) -> Response:
        roles = get_routing_roles(team_id=self.team.id)
        return Response(
            SignalRoutingRoleSerializer(
                [
                    {"id": role.id, "name": role.name, "is_member": request.user.id in role.member_user_ids}
                    for role in roles
                ],
                many=True,
            ).data
        )


class SignalDomainPreferenceViewSet(mixins.ListModelMixin, _OwnershipViewSet):
    serializer_class = SignalDomainPreferenceSerializer
    queryset = SignalDomainPreference.objects.unscoped().select_related("domain__owning_role").order_by("domain__name")

    def safely_get_queryset(self, queryset):
        return queryset.filter(user=self.request.user, team=self.team)

    @extend_schema(responses=SignalRoutingSuggestionSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def suggestions(self, request: Request, **kwargs) -> Response:
        user = self.require_personal_action()
        return Response(
            SignalRoutingSuggestionSerializer(
                suggested_domain_preferences(team_id=self.team.id, user=user), many=True
            ).data
        )

    @validated_request(
        request_serializer=SignalDomainPreferenceWriteSerializer, responses={200: SignalDomainPreferenceSerializer}
    )
    @action(detail=False, methods=["post"])
    def set(self, request: ValidatedRequest, **kwargs) -> Response:
        user = self.require_personal_action()
        get_object_or_404(SignalProductDomain.objects.for_team(self.team.id), id=request.validated_data["domain_id"])
        preference = DomainPreferenceService(team_id=self.team.id, user=user).set_excluded(**request.validated_data)
        capture_routing_change(team_id=self.team.id, action="preference")
        return Response(SignalDomainPreferenceSerializer(preference).data)

    @validated_request(request_serializer=SignalDomainPreviewSerializer, responses={201: SignalRoutingBatchSerializer})
    @action(detail=False, methods=["post"])
    def preview(self, request: ValidatedRequest, **kwargs) -> Response:
        user = self.require_personal_action()
        get_object_or_404(
            SignalProductDomain.objects.for_team(self.team.id), id=request.validated_data["domain_id"], archived=False
        )
        batch = DomainPreferenceService(team_id=self.team.id, user=user).preview(**request.validated_data)
        capture_routing_change(team_id=self.team.id, action="preview")
        return Response(SignalRoutingBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class SignalRoutingBatchViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, _OwnershipViewSet):
    serializer_class = SignalRoutingBatchSerializer
    queryset = SignalRoutingBatch.objects.unscoped().select_related("preference").order_by("-created_at")

    def safely_get_queryset(self, queryset):
        return queryset.filter(preference__user=self.request.user, team=self.team)

    @extend_schema(request=None, responses={200: SignalRoutingBatchSerializer})
    @action(detail=True, methods=["post"])
    def apply(self, request: Request, pk=None, **kwargs) -> Response:
        user = self.require_personal_action()
        batch = self.get_object()
        applied = DomainPreferenceService(team_id=self.team.id, user=user).apply(batch_id=batch.id)
        capture_routing_change(team_id=self.team.id, action="apply")
        return Response(SignalRoutingBatchSerializer(applied).data)

    @extend_schema(request=None, responses={200: SignalRoutingBatchSerializer})
    @action(detail=True, methods=["post"])
    def undo(self, request: Request, pk=None, **kwargs) -> Response:
        user = self.require_personal_action()
        batch = self.get_object()
        undone = DomainPreferenceService(team_id=self.team.id, user=user).undo(batch_id=batch.id)
        capture_routing_change(team_id=self.team.id, action="undo")
        return Response(SignalRoutingBatchSerializer(undone).data)

    @extend_schema(request=None, responses={200: SignalRoutingBatchSerializer})
    @action(detail=True, methods=["post"])
    def retry(self, request: Request, pk=None, **kwargs) -> Response:
        user = self.require_personal_action()
        batch = self.get_object()
        retried = DomainPreferenceService(team_id=self.team.id, user=user).retry(batch_id=batch.id)
        capture_routing_change(team_id=self.team.id, action="retry")
        return Response(SignalRoutingBatchSerializer(retried).data)

    @extend_schema(responses=SignalRoutingBatchReportSerializer(many=True))
    @action(detail=True, methods=["get"])
    def reports(self, request: Request, pk=None, **kwargs) -> Response:
        batch = self.get_object()
        queryset = (
            SignalRoutingBatchChange.objects.for_team(self.team.id)
            .filter(batch=batch)
            .select_related("report")
            .order_by("id")
        )
        page = self.paginate_queryset(queryset)
        changes = list(page if page is not None else queryset)
        claims = get_active_claims(team_id=self.team.id, report_ids=[str(change.report_id) for change in changes])
        for change in changes:
            claim = claims.get(str(change.report_id))
            owner = responsible_user(claim) if claim else None
            change.has_active_claim = owner is not None and owner.id == request.user.id
        data = SignalRoutingBatchReportSerializer(changes, many=True).data
        return self.get_paginated_response(data) if page is not None else Response(data)


@extend_schema_serializer(many=False)
class SignalReportRoutingStateSerializer(serializers.Serializer):
    routing = SignalReportRoutingSerializer(
        allow_null=True, help_text="Current accepted or proposed domain/team routing."
    )
    proposals = SignalRoutingProposalSerializer(
        many=True, read_only=True, help_text="Shadow classifications for review. They do not change accepted ownership."
    )
    personal = SignalPersonalCorrectionSerializer(help_text="The current user's correction and active ownership.")


@extend_schema(parameters=[OpenApiParameter("report_id", OpenApiTypes.UUID, OpenApiParameter.PATH)])
class SignalReportRoutingViewSet(_OwnershipViewSet):
    serializer_class = SignalReportRoutingStateSerializer
    queryset = SignalReport.objects.all()
    pagination_class = None

    def report(self) -> SignalReport:
        try:
            report_id = UUID(str(self.parents_query_dict["report_id"]))
        except (ValueError, TypeError):
            raise NotFound()
        return get_object_or_404(
            SignalReport.objects.filter(team=self.team).exclude(status=SignalReport.Status.DELETED),
            id=report_id,
        )

    def state(self, report: SignalReport) -> dict:
        user = cast(User, self.request.user)
        routing = (
            SignalReportRouting.objects.for_team(self.team.id)
            .filter(report=report)
            .select_related("domain__owning_role", "owning_role")
            .first()
        )
        claim = get_active_claim(team_id=self.team.id, report_id=report.id)
        owner = responsible_user(claim) if claim else None
        return SignalReportRoutingStateSerializer(
            {
                "routing": routing,
                "proposals": SignalRoutingProposal.objects.for_team(self.team.id)
                .filter(report=report)
                .select_related("domain__owning_role")
                .order_by("method"),
                "personal": {
                    "excluded": SignalReviewerExclusion.objects.for_team(self.team.id)
                    .filter(report=report, user_id=user.id)
                    .exists(),
                    "has_active_claim": owner is not None and owner.id == user.id,
                },
            }
        ).data

    @extend_schema(responses={200: SignalReportRoutingStateSerializer})
    def list(self, request: Request, **kwargs) -> Response:
        return Response(self.state(self.report()))

    @validated_request(
        request_serializer=SignalRoutingCorrectionSerializer, responses={200: SignalReportRoutingStateSerializer}
    )
    def create(self, request: ValidatedRequest, **kwargs) -> Response:
        user = self.require_personal_action()
        report = self.report()
        data = request.validated_data
        domain = (
            get_object_or_404(SignalProductDomain.objects.for_team(self.team.id), id=data["domain_id"], archived=False)
            if data["domain_id"]
            else None
        )
        role_id = data.get("owning_role_id", domain.owning_role_id if domain else None)
        roles = {role.id: role for role in get_routing_roles(team_id=self.team.id)}
        if role_id is not None and role_id not in roles:
            raise serializers.ValidationError({"owning_role_id": "Choose a team from this project's organization."})
        with transaction.atomic():
            SignalReport.objects.select_for_update().get(team=self.team, id=report.id)
            SignalReportRouting.objects.for_team(self.team.id).update_or_create(
                team_id=self.team.id,
                report=report,
                defaults={
                    "domain": domain,
                    "owning_role_id": role_id,
                    "source": SignalReportRouting.Source.HUMAN,
                    "explanation": data["explanation"],
                    "human_override": True,
                    "accepted": domain is not None,
                    "domain_revision": domain.revision if domain else None,
                    "confidence": None,
                    "classifier_version": "",
                },
            )
            SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(report.id),
                content=NoteArtefact(
                    note=f"Routing updated: {domain.name if domain else 'Unclassified'}; {roles[role_id].name if role_id else 'No team'}.",
                ),
                attribution=ArtefactAttribution.from_user(user.id),
            )
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(report.id),
                content=current_eligible_reviewers(team_id=self.team.id, report_id=report.id),
                attribution=ArtefactAttribution.from_user(user.id),
                reevaluate_autostart=False,
            )
        capture_routing_change(team_id=self.team.id, action="correct")
        return Response(self.state(report))

    @validated_request(
        request_serializer=SignalRoutingProposalWriteSerializer, responses={200: SignalRoutingProposalSerializer}
    )
    @action(detail=False, methods=["post"])
    def propose(self, request: ValidatedRequest, **kwargs) -> Response:
        report = self.report()
        proposal = record_routing_proposal(team_id=self.team.id, report_id=report.id, data=request.validated_data)
        return Response(SignalRoutingProposalSerializer(proposal).data)

    @extend_schema(request=None, responses={200: SignalReportRoutingStateSerializer})
    @action(detail=False, methods=["post"], url_path="not_me")
    def not_me(self, request: Request, **kwargs) -> Response:
        user = self.require_personal_action()
        report = self.report()
        scoped_team_ids = get_authenticator_scoped_team_ids(request.successful_authenticator)
        remove_my_suggestion(
            team=self.team,
            report_id=report.id,
            user=user,
            scoped_team_ids=tuple(scoped_team_ids) if scoped_team_ids is not None else None,
        )
        capture_routing_change(team_id=self.team.id, action="not_me")
        return Response(self.state(report))

    @extend_schema(request=None, responses={200: SignalReportRoutingStateSerializer})
    @action(detail=False, methods=["post"])
    def restore(self, request: Request, **kwargs) -> Response:
        user = self.require_personal_action()
        report = self.report()
        with transaction.atomic():
            SignalReport.objects.select_for_update().get(team=self.team, id=report.id)
            policy = ReviewerRoutingPolicy(team_id=self.team.id, report_id=report.id)
            policy.lock_domain()
            SignalReviewerExclusion.objects.for_team(self.team.id).filter(report=report, user=user).delete()
            if not policy.allows_user(user.id):
                raise serializers.ValidationError(
                    "A domain rule still applies. Update your routing or take ownership of this report."
                )
            content = current_eligible_reviewers(team_id=self.team.id, report_id=report.id)
            if not any(entry.user_uuid == str(user.uuid) for entry in content.root):
                content.root.append(
                    SuggestedReviewerEntry(
                        user_uuid=str(user.uuid),
                        github_login=user.get_github_login(),
                        reason="Restored by the suggested owner.",
                    )
                )
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(report.id),
                content=content,
                attribution=ArtefactAttribution.from_user(user.id),
                reevaluate_autostart=False,
            )
        capture_routing_change(team_id=self.team.id, action="restore")
        return Response(self.state(report))
