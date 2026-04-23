from typing import cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, permissions, status, viewsets
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import is_cloud, is_dev_mode
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from ..facade import api, contracts
from .serializers import CreateLegalDocumentSerializer, LegalDocumentSerializer


class IsCloudOrDevDeployment(BasePermission):
    """
    Gates the legal-documents API to cloud (or a local DEBUG environment, so
    we can test the flow). Self-hosted production deployments don't have the
    PandaDoc / Slack credentials and the feature is a PostHog-owned workflow,
    not something customers run on their own infrastructure.
    """

    message = "Legal documents are only available on PostHog Cloud."

    def has_permission(self, request: Request, view) -> bool:
        if not (is_cloud() or is_dev_mode()):
            raise exceptions.NotFound("Not found.")
        return True


class IsOrganizationAdminOrOwner(BasePermission):
    """
    Allow access only to organization admins and owners (for every method,
    including reads). Mirrors the gate we apply to the Settings → Legal
    documents entry and the /legal scene in the frontend, so that non-admin
    members can't probe the API directly either.
    """

    message = "Your organization access level is insufficient."

    def has_permission(self, request: Request, view) -> bool:
        organization = getattr(view, "organization", None)
        if organization is None:
            # Mixin hasn't resolved the org yet — defer. TeamAndOrgViewSetMixin
            # calls this after the URL kwarg has been parsed, so this branch is
            # effectively only hit on misconfigured routes.
            raise exceptions.NotFound("Organization not found.")
        try:
            membership = OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization)
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound("Organization not found.")
        return membership.level >= OrganizationMembership.Level.ADMIN


@extend_schema(tags=["core"])
class LegalDocumentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "legal_document"
    permission_classes = [IsCloudOrDevDeployment, permissions.IsAuthenticated, IsOrganizationAdminOrOwner]

    @extend_schema(responses={200: LegalDocumentSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        documents = api.list_for_organization(self.organization.id)
        page = self.paginate_queryset(documents)
        if page is not None:
            return self.get_paginated_response(LegalDocumentSerializer(instance=page, many=True).data)
        return Response(LegalDocumentSerializer(instance=documents, many=True).data)

    @extend_schema(
        request=CreateLegalDocumentSerializer,
        responses={201: LegalDocumentSerializer},
    )
    def create(self, request: Request, **kwargs) -> Response:
        serializer = CreateLegalDocumentSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        dto = api.create_document(
            contracts.CreateLegalDocumentInput(
                organization_id=self.organization.id,
                created_by_id=user.id,
                distinct_id=str(user.distinct_id),
                document_type=serializer.validated_data["document_type"],
                company_name=serializer.validated_data["company_name"],
                company_address=serializer.validated_data["company_address"],
                representative_email=serializer.validated_data["representative_email"],
            )
        )
        return Response(LegalDocumentSerializer(instance=dto).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: LegalDocumentSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            document_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        dto = api.get_for_organization(document_id, self.organization.id)
        if dto is None:
            raise exceptions.NotFound()
        return Response(LegalDocumentSerializer(instance=dto).data)
