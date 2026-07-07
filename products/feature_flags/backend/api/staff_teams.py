from django.db.models import F, Q

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import request, response, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.models.team import Team
from posthog.permissions import IsStaffUser

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
MIN_SEARCH_LENGTH = 2


class StaffTeamSearchQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        help_text=(
            "Search string matched against team id (exact), api_token (exact), team name (partial), "
            f"or organization name (partial). Non-numeric queries must be at least {MIN_SEARCH_LENGTH} "
            "characters so an empty or single-letter query never returns half the table; a numeric team-id "
            "lookup is allowed at a single digit."
        ),
    )
    limit = serializers.IntegerField(
        required=False,
        default=DEFAULT_LIMIT,
        min_value=1,
        max_value=MAX_LIMIT,
        help_text=f"Maximum number of teams to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).",
    )

    def validate_search(self, value: str) -> str:
        stripped = value.strip()
        # Digit-only queries are exact team-id lookups (Q(id=...) below) and are allowed at a
        # single digit so deep links to low-id teams resolve; everything else needs >= 2 chars.
        # isdecimal() (not isdigit()) since isdigit() also accepts non-ASCII digit-like characters
        # (e.g. superscript "²") that int() can't parse, which would 500 below.
        min_length = 1 if stripped.isdecimal() else MIN_SEARCH_LENGTH
        if len(stripped) < min_length:
            raise serializers.ValidationError(
                f"Search must be at least {MIN_SEARCH_LENGTH} characters, or a numeric team id."
            )
        return stripped


class StaffTeamResultSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Team id.")
    name = serializers.CharField(help_text="Team name.")
    api_token = serializers.CharField(help_text="Team api_token (used as the flags evaluation cache key).")
    organization_id = serializers.CharField(help_text="Organization uuid that owns the team.")
    organization_name = serializers.CharField(help_text="Organization name that owns the team.")
    project_id = serializers.IntegerField(help_text="Project id the team belongs to.")


@extend_schema_serializer(many=False)
class StaffTeamSearchResponseSerializer(serializers.Serializer):
    results = StaffTeamResultSerializer(many=True, help_text="Matching teams.")


class FeatureFlagsStaffTeamSearchViewSet(viewsets.ViewSet):
    """
    Staff-only, unscoped team search across every organization.

    Unlike TeamViewSet (membership-scoped via TeamAndOrgViewSetMixin), staff need to look up
    teams they do not belong to in order to inspect and rebuild flag caches. Registered on the
    root router so it is not team-nested. Exposes the same fields Django admin's TeamAdmin
    already shows staff un-redacted, so no new data exposure.
    """

    # Not part of the public API scope model: access is gated entirely by IsStaffUser below,
    # not by a personal-API-key scope, so this stays out of the public OpenAPI/generated-client
    # surface (see posthog/api/documentation.py's INTERNAL handling).
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]

    @validated_request(
        query_serializer=StaffTeamSearchQuerySerializer,
        responses={200: OpenApiResponse(response=StaffTeamSearchResponseSerializer)},
    )
    def list(self, request: request.Request, **kwargs) -> response.Response:
        search: str = request.validated_query_data["search"]
        limit: int = request.validated_query_data["limit"]

        query = Q(name__icontains=search) | Q(api_token=search) | Q(organization__name__icontains=search)
        if search.isdecimal():
            query |= Q(id=int(search))

        # icontains on name/organization__name forces a sequential scan (no btree-usable index);
        # acceptable today given staff-only, low-frequency usage. Revisit with a pg_trgm index if
        # this shows up in slow-query logs.
        # .values() keys are aliased to match the serializer fields, so the rows serialize
        # directly (the response serializer stringifies the organization UUID).
        teams = (
            Team.objects.filter(query)
            .annotate(organization_name=F("organization__name"))
            .order_by("id")
            .values("id", "name", "api_token", "organization_id", "organization_name", "project_id")[:limit]
        )

        return response.Response(StaffTeamSearchResponseSerializer({"results": list(teams)}).data)
