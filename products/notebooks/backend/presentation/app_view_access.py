from functools import cached_property
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache

from rest_framework import serializers
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.auth import SessionAuthentication
from posthog.ip_restrictions import IPRestrictionsPermission
from posthog.models.team import Team
from posthog.permissions import (
    ActiveOrganizationPermission,
    TwoFactorEnforcementPermission,
    VerifiedDomainEnforcementPermission,
)

from products.notebooks.backend.facade.app_delivery import check_app_view_budget, read_granted_output
from products.notebooks.backend.presentation.app_serializers import notebook_app_builder_enabled


class AppViewGrantRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=False, help_text="Email address of the project member who can open the published output."
    )
    recipient_uuid = serializers.UUIDField(
        required=False, help_text="Current recipient to revoke, even if their email changed."
    )
    revision = serializers.IntegerField(
        min_value=1, required=False, help_text="The displayed release to share. Required when granting access."
    )
    revoke = serializers.BooleanField(
        default=False, help_text="Remove this member's access to every revision of this app."
    )

    def validate(self, attrs):
        if not attrs.get("email") and not (attrs.get("revoke") and attrs.get("recipient_uuid")):
            raise serializers.ValidationError("Enter a member email or choose a recipient to revoke.")
        return attrs


class ActiveAppViewGrantSerializer(serializers.Serializer):
    recipient_uuid = serializers.UUIDField()
    email = serializers.EmailField()
    revision = serializers.IntegerField()
    expires_at = serializers.DateTimeField()


class AppViewGrantResultSerializer(serializers.Serializer):
    url = serializers.CharField(allow_null=True, help_text="Recipient-specific path for the pinned release.")
    expires_at = serializers.DateTimeField(allow_null=True, help_text="When this app-only grant expires.")


class AppOutputProjectMember(BasePermission):
    def has_permission(self, request, view) -> bool:
        check_app_view_budget(request.user.pk)
        if not view.team.all_users_with_access(user_uuids=[str(request.user.uuid)]).exists():
            raise Http404()
        return True


class GrantedAppOutputView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        IsAuthenticated,
        AppOutputProjectMember,
        IPRestrictionsPermission,
        VerifiedDomainEnforcementPermission,
        TwoFactorEnforcementPermission,
        ActiveOrganizationPermission,
    ]
    parent_query_kwargs = ["team_id"]

    @cached_property
    def team(self) -> Team:
        return get_object_or_404(Team.objects.select_related("organization"), pk=self.kwargs["team_id"])

    def get(self, request: Request, team_id: int, grant_id: UUID) -> HttpResponse:
        if request.user.pk is None or not notebook_app_builder_enabled(request.user, self.team):
            raise Http404()
        output = read_granted_output(self.team.pk, request.user.pk, grant_id)
        if output is None:
            raise Http404()
        tabs = output.tabs
        active = next((index for index in range(len(tabs)) if str(index) == request.GET.get("tab")), 0)
        return render(
            request,
            "notebooks/app_output.html",
            {
                "title": output.title,
                "description": output.description,
                "revision": output.revision,
                "published_at": output.published_at,
                "tabs": tabs,
                "active": active,
                "blocks": tabs[active].blocks if tabs else [],
            },
        )


notebook_app_view_grant = never_cache(login_required(GrantedAppOutputView.as_view()))
