from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from rest_framework import serializers

from posthog.models.team import Team

from products.notebooks.backend.facade.app_delivery import read_granted_output
from products.notebooks.backend.presentation.app_serializers import notebook_app_builder_enabled


class AppViewGrantRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Email address of the project member who can open the published output.")
    revoke = serializers.BooleanField(
        default=False, help_text="Remove this member's access to every revision of this app."
    )


class AppViewGrantResultSerializer(serializers.Serializer):
    url = serializers.CharField(allow_null=True, help_text="Recipient-specific path for the pinned release.")
    expires_at = serializers.DateTimeField(allow_null=True, help_text="When this app-only grant expires.")


@require_GET
@never_cache
@login_required
def notebook_app_view_grant(request: HttpRequest, team_id: int, grant_id: UUID) -> HttpResponse:
    team = get_object_or_404(Team.objects.select_related("organization"), pk=team_id)
    if not notebook_app_builder_enabled(request.user, team):
        raise Http404()
    output = read_granted_output(team.pk, request.user.pk, grant_id)
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
