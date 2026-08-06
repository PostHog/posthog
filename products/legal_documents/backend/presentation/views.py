from typing import cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponseRedirect

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from ..facade import api, contracts
from .permissions import IsCloudOrDevDeployment, IsOrganizationAdminOrOwner
from .serializers import CreateLegalDocumentSerializer, LegalDocumentSerializer


class _PandaDocUnavailable(exceptions.APIException):
    """503 surfaced when a self-serve delete couldn't cancel the PandaDoc envelope."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = (
        "Couldn't cancel the PandaDoc envelope. Please try again, or contact PostHog support if this keeps happening."
    )
    default_code = "legal_document_void_failed"


class LegalDocumentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "legal_document"
    permission_classes = [IsCloudOrDevDeployment, permissions.IsAuthenticated, IsOrganizationAdminOrOwner]

    def dangerously_get_permissions(self) -> list[permissions.BasePermission]:
        # Staff users (Django admin) need to download signed PDFs from the
        # admin change view without first joining the customer's organization.
        # The default permission chain adds OrganizationMemberPermissions which
        # rejects them; bypass it here for the download action only. The
        # download still scopes by URL-provided org_id inside the view, so a
        # staff user can't grab a document that doesn't belong to that org.
        if self.action == "download" and getattr(self.request.user, "is_staff", False):
            return [IsCloudOrDevDeployment(), permissions.IsAuthenticated()]
        raise NotImplementedError()

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

    @extend_schema(responses={302: None, 404: None})
    @action(detail=True, methods=["GET"], url_path="download")
    def download(self, request: Request, pk: str, **kwargs) -> HttpResponseRedirect:
        """
        Short-lived redirect to the signed PDF in object storage. 404 while the
        envelope is still out for signature (or if the upload hasn't completed
        yet). The underlying presigned URL expires in ~60s; clients should hit
        this endpoint each time they want to view the PDF rather than caching.
        """
        try:
            document_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        presigned_url = api.get_signed_pdf_download_url(document_id, self.organization.id)
        if not presigned_url:
            raise exceptions.NotFound()
        return HttpResponseRedirect(presigned_url)

    @extend_schema(responses={204: None, 403: None, 404: None, 503: None})
    def destroy(self, request: Request, pk: str, **kwargs) -> Response:
        """
        Delete an unsigned legal document. The PandaDoc envelope is voided
        first so the original signer can no longer complete it; only if that
        succeeds is the row removed, freeing the unique-per-org-per-type
        constraint so a fresh document can be generated.

        Returns 503 if the PandaDoc void fails — the row stays in that case
        and the frontend should prompt the user to retry. Returns 403 for
        signed documents (legal artifacts; staff can still delete signed
        rows from Django admin).
        """
        try:
            document_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        try:
            api.delete_document(document_id, self.organization.id)
        except api.LegalDocumentNotFound:
            raise exceptions.NotFound()
        except api.LegalDocumentAlreadySigned:
            raise exceptions.PermissionDenied(
                "Signed documents can't be deleted from the UI. Contact PostHog support if you need to remove a signed record."
            )
        except api.LegalDocumentVoidFailed:
            raise _PandaDocUnavailable()
        return Response(status=status.HTTP_204_NO_CONTENT)
