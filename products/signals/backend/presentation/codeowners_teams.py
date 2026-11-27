from __future__ import annotations

import dataclasses
from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission

from products.access_control.backend.facade.contracts import RoleMatchSource
from products.signals.backend.facade.github import InvalidCodeownersRepositoryError, scan_team_codeowners
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission


class CodeownersTeamsQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text=(
            "Optional GitHub repository in `organization/repository` form to scan. "
            "When omitted, scans up to 10 non-archived connected repositories."
        ),
    )


class CodeownersTeamSerializer(serializers.Serializer):
    provider_organization_id = serializers.CharField(
        read_only=True,
        help_text="Lowercased GitHub organization or owner login from the CODEOWNERS entry.",
    )
    team_slug = serializers.CharField(
        read_only=True,
        help_text="Lowercased GitHub team slug from the CODEOWNERS entry.",
    )
    handle = serializers.CharField(
        read_only=True,
        help_text="Canonical `@organization/team-slug` handle.",
    )
    repositories = serializers.ListField(
        child=serializers.CharField(help_text="Repository `owner/name` where the team was found."),
        read_only=True,
        help_text="Connected repositories whose CODEOWNERS file named this team.",
    )
    likely_role_id = serializers.UUIDField(
        allow_null=True,
        read_only=True,
        help_text="PostHog role UUID resolved by `likely_role`, or null when no role matched.",
    )
    likely_role_name = serializers.CharField(
        allow_null=True,
        read_only=True,
        help_text="Display name of the resolved PostHog role, or null when no role matched.",
    )
    match_source = serializers.ChoiceField(
        choices=RoleMatchSource.choices,
        allow_null=True,
        read_only=True,
        help_text="How `likely_role` resolved the PostHog role: `external_reference` or `name_match`.",
    )


@extend_schema_serializer(many=False)
class CodeownersTeamsResponseSerializer(serializers.Serializer):
    teams = CodeownersTeamSerializer(
        many=True,
        read_only=True,
        help_text="GitHub teams discovered in CODEOWNERS across the scanned repositories.",
    )
    scanned_repository_count = serializers.IntegerField(
        read_only=True,
        help_text="Number of connected repositories whose CODEOWNERS files were checked.",
    )
    total_repository_count = serializers.IntegerField(
        read_only=True,
        help_text="Total connected non-archived repositories available to scan.",
    )


class CodeownersTeamsErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the request failed.")


class SignalCodeownersTeamsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = CodeownersTeamsResponseSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "inbox"
    requires_resource_level_access = True
    pagination_class = None

    @extend_schema(
        summary="Scan CODEOWNERS teams for PostHog role mapping",
        description=(
            "Scan CODEOWNERS files from the project's connected GitHub repositories, return discovered "
            "`@organization/team-slug` handles, and resolve each handle's `likely_role` in the organization."
        ),
        parameters=[CodeownersTeamsQuerySerializer],
        responses={
            200: CodeownersTeamsResponseSerializer,
            400: CodeownersTeamsErrorSerializer,
        },
        operation_id="signals_codeowners_teams_list",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = CodeownersTeamsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        canonical_team = self.team.parent_team or self.team
        repository = query.validated_data.get("repository") or None
        try:
            scan = scan_team_codeowners(canonical_team, repository=repository)
        except InvalidCodeownersRepositoryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = {
            "teams": [dataclasses.asdict(entry) for entry in scan.teams],
            "scanned_repository_count": scan.scanned_repository_count,
            "total_repository_count": scan.total_repository_count,
        }
        return Response(CodeownersTeamsResponseSerializer(payload).data)
