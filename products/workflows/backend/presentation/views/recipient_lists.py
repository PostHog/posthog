from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication

from products.workflows.backend.facade.recipient_lists import (
    MAX_RECIPIENT_LIST_ROWS,
    RecipientListInvalid,
    RecipientListNotFound,
    create_recipient_list,
    get_recipient_list,
    get_recipient_list_page,
)
from products.workflows.backend.facade.service_jwt import WORKFLOW_RECIPIENT_LIST_PURPOSE


class RecipientListCreateSerializer(serializers.Serializer):
    rows = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField(allow_blank=True)),
        max_length=MAX_RECIPIENT_LIST_ROWS,
        help_text=(
            'One object per recipient. Each needs "email"; "distinct_id" is optional and matches the row '
            "to that person. Every other key becomes {{ variables.<key> }} for that recipient."
        ),
    )


class RecipientListSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Set as filters.recipient_list_id on a batch trigger to send to this list.")
    row_count = serializers.IntegerField(help_text="Recipients kept.")
    columns = serializers.ListField(
        child=serializers.CharField(), help_text="Variable names available to each recipient's message."
    )
    dropped_invalid_email = serializers.IntegerField(help_text="Rows dropped for a missing or invalid email.")
    dropped_duplicate_email = serializers.IntegerField(help_text="Rows dropped because an earlier row had the email.")
    dropped_too_large = serializers.IntegerField(help_text="Rows dropped for holding more than 4KB of data.")


class WorkflowRecipientListViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "hog_flow"
    # No workflow is loaded here, so a grant on one workflow must not open every list in the project.
    requires_resource_level_access = True
    serializer_class = RecipientListCreateSerializer

    @extend_schema(
        request=RecipientListCreateSerializer,
        responses={201: RecipientListSerializer},
        summary="Save a recipient list for a batch workflow",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = RecipientListCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            summary = create_recipient_list(team_id=self.team_id, rows=serializer.validated_data["rows"])
        except RecipientListInvalid as error:
            raise exceptions.ValidationError(str(error))
        return Response(RecipientListSerializer(summary).data, status=201)

    @extend_schema(responses=RecipientListSerializer, summary="Get a recipient list's size and columns")
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        summary = get_recipient_list(team_id=self.team_id, list_id=pk)
        if summary is None:
            raise exceptions.NotFound("Recipient list not found.")
        return Response(RecipientListSerializer(summary).data)


class RecipientListPagesJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_RECIPIENT_LIST_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # The list is identified by the verified token, never by the request body, so a token
        # minted for one list can't read another.
        if not claims.get("recipient_list_id"):
            raise AuthenticationFailed("Service token is missing its recipient list claim.")
        return user, str(claims["recipient_list_id"])


class RecipientListPageRequestSerializer(serializers.Serializer):
    cursor = serializers.CharField(
        required=False, allow_null=True, help_text="Cursor from the previous page, or null for the first page."
    )


class RecipientListRecipientSerializer(serializers.Serializer):
    email = serializers.CharField(help_text="Address the message goes to.")
    person_id = serializers.CharField(allow_null=True, help_text="Person matched by email, or null.")
    distinct_id = serializers.CharField(allow_null=True, help_text="The row's distinct ID when a person owns it.")
    variables = serializers.DictField(child=serializers.CharField(allow_blank=True), help_text="The row's columns.")


class RecipientListPageSerializer(serializers.Serializer):
    recipients = RecipientListRecipientSerializer(many=True, help_text="Recipients in this page, in list order.")
    cursor = serializers.CharField(allow_null=True, help_text="Cursor for the next page, or null on the last page.")
    has_more = serializers.BooleanField(help_text="Whether another page follows.")


class WorkflowRecipientListPageViewSet(viewsets.GenericViewSet):
    """Pages a recipient list for the plugin server's batch resolver. Authenticated by a scoped
    service JWT that names the team and the list, never by a user credential."""

    authentication_classes = [RecipientListPagesJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = RecipientListPageRequestSerializer

    @extend_schema(
        request=RecipientListPageRequestSerializer,
        responses=RecipientListPageSerializer,
        summary="Read one page of a recipient list",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = RecipientListPageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)
        try:
            page = get_recipient_list_page(
                team_id=team_id, list_id=cast(str, request.auth), cursor=serializer.validated_data.get("cursor")
            )
        except RecipientListNotFound:
            raise exceptions.NotFound("Recipient list not found.")
        except RecipientListInvalid as error:
            raise exceptions.ValidationError(str(error))
        return Response(RecipientListPageSerializer(page).data)
