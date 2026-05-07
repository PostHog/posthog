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
