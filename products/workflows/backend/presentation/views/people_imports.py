from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.workflows.backend.facade.people_import import (
    MAX_PEOPLE_IMPORT_ROWS,
    PeopleImportInvalid,
    start_people_import,
)


class PeopleImportCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=400, help_text="Name of the static cohort that holds the imported people.")
    rows = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField(allow_blank=True)),
        max_length=MAX_PEOPLE_IMPORT_ROWS,
        help_text=(
            'One object per person. Each needs "email". An optional "distinct_id" picks the person to update or '
            "create; without it, the row updates the person with that email, or creates one keyed by the email. "
            "Every other key is set as a person property."
        ),
    )


class PeopleImportSerializer(serializers.Serializer):
    cohort_id = serializers.IntegerField(help_text="The static cohort that fills with the imported people.")
    row_count = serializers.IntegerField(help_text="People created or updated.")
    new_people = serializers.IntegerField(help_text="Rows that create a person who isn't in PostHog yet.")
    columns = serializers.ListField(child=serializers.CharField(), help_text="Person properties the rows set.")
    dropped_invalid_email = serializers.IntegerField(help_text="Rows dropped for a missing or invalid email.")
    dropped_duplicate_email = serializers.IntegerField(
        help_text="Rows dropped because an earlier row had the email or distinct ID."
    )
    dropped_too_large = serializers.IntegerField(help_text="Rows dropped for holding more than 4KB of data.")


class WorkflowPeopleImportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # The import creates a cohort and sets person properties, so it needs both write scopes.
    scope_object = "cohort"
    required_scopes = ["cohort:write", "person:write"]
    serializer_class = PeopleImportCreateSerializer

    @extend_schema(
        request=PeopleImportCreateSerializer,
        responses={201: PeopleImportSerializer},
        summary="Create or update people from rows and add them to a new static cohort",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Session users skip API scopes, and access control checks only the cohort scope_object.
        if not self.user_access_control.check_access_level_for_resource("person", "editor"):
            raise exceptions.PermissionDenied("You need edit access to persons to import people.")
        serializer = PeopleImportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            summary = start_people_import(
                team=self.team,
                user=cast(User, request.user),
                name=serializer.validated_data["name"],
                rows=serializer.validated_data["rows"],
            )
        except PeopleImportInvalid as error:
            raise exceptions.ValidationError(str(error))
        return Response(PeopleImportSerializer(summary).data, status=201)
