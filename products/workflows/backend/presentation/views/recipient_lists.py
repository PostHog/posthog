from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.workflows.backend.facade.recipient_lists import (
    MAX_RECIPIENT_LIST_ROWS,
    RecipientListInvalid,
    recipient_lists_for_cohorts,
    start_recipient_list_import,
)


class RecipientListCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=400, help_text="Name of the static cohort that holds the list's people.")
    rows = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField(allow_blank=True)),
        max_length=MAX_RECIPIENT_LIST_ROWS,
        help_text=(
            'One object per person. Each needs "email". An optional "distinct_id" picks the person, and an "id" '
            'column counts as the distinct_id when there is no "distinct_id" column. Without either, the row '
            "matches the person with that email, or creates one keyed by the email. Every other key is kept on "
            "the list, and a broadcast to the list's cohort reads it as {{ variables.<key> }}. Keys are never set "
            "as person properties."
        ),
    )


class RecipientListSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The recipient list.")
    cohort_id = serializers.IntegerField(help_text="The static cohort that fills with the list's people.")
    row_count = serializers.IntegerField(help_text="People in the list.")
    new_people = serializers.IntegerField(help_text="Rows that create a person who isn't in PostHog yet.")
    columns = serializers.ListField(
        child=serializers.CharField(), help_text="Columns a broadcast template reads as {{ variables.<column> }}."
    )
    dropped_invalid_email = serializers.IntegerField(help_text="Rows dropped for a missing or invalid email.")
    dropped_duplicate_email = serializers.IntegerField(
        help_text="Rows dropped because an earlier row had the email or distinct ID."
    )
    dropped_too_large = serializers.IntegerField(help_text="Rows dropped for holding more than 4KB of data.")


MAX_LOOKUP_COHORTS = 100


class RecipientListLookupSerializer(serializers.Serializer):
    cohort_ids = serializers.CharField(help_text="Comma-separated IDs of the cohorts to find uploaded lists for.")

    def validate_cohort_ids(self, value: str) -> list[int]:
        try:
            cohort_ids = [int(part) for part in value.split(",") if part.strip()]
        except ValueError:
            raise serializers.ValidationError("Use cohort IDs separated by commas.")
        if len(cohort_ids) > MAX_LOOKUP_COHORTS:
            raise serializers.ValidationError(f"Look up at most {MAX_LOOKUP_COHORTS} cohorts at once.")
        return cohort_ids


class RecipientListColumnsSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The recipient list.")
    cohort_id = serializers.IntegerField(help_text="The static cohort that holds the list's people.")
    columns = serializers.ListField(
        child=serializers.CharField(), help_text="Columns a broadcast template reads as {{ variables.<column> }}."
    )


class WorkflowRecipientListViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "cohort"
    serializer_class = RecipientListCreateSerializer
    # A lookup returns at most one list per cohort asked for, so there is nothing to page.
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        # Reading a list's columns is a cohort read. The upload creates a cohort and can create people.
        return ["cohort:read"] if self.action == "list" else ["cohort:write", "person:write"]

    @extend_schema(
        parameters=[RecipientListLookupSerializer],
        responses={200: RecipientListColumnsSerializer(many=True)},
        summary="Find the uploaded recipient lists behind cohorts, with the columns a broadcast can use",
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        query = RecipientListLookupSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        recipient_lists = recipient_lists_for_cohorts(self.team.id, query.validated_data["cohort_ids"])
        return Response(RecipientListColumnsSerializer(recipient_lists, many=True).data)

    @extend_schema(
        request=RecipientListCreateSerializer,
        responses={201: RecipientListSerializer},
        summary="Upload a recipient list: its people join a new static cohort, and its columns become broadcast variables",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Session users skip API scopes, and access control checks only the cohort scope_object.
        if not self.user_access_control.check_access_level_for_resource("person", "editor"):
            raise exceptions.PermissionDenied("You need edit access to persons to upload a recipient list.")
        serializer = RecipientListCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            summary = start_recipient_list_import(
                team=self.team,
                user=cast(User, request.user),
                name=serializer.validated_data["name"],
                rows=serializer.validated_data["rows"],
            )
        except RecipientListInvalid as error:
            raise exceptions.ValidationError(str(error))
        return Response(RecipientListSerializer(summary).data, status=201)
