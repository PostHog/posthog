from urllib.parse import urlsplit
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from rest_framework import serializers

from posthog.models import Team, User

from products.notebooks.backend.facade.app_embeds import read_embed_audience, redeem_signed_embed
from products.notebooks.backend.presentation.app_serializers import notebook_app_builder_enabled


class AppEmbedRequestSerializer(serializers.Serializer):
    origin = serializers.URLField(
        max_length=255, help_text="Exact HTTPS origin that may frame the embed, without a path."
    )
    tenant_column = serializers.CharField(
        max_length=120, help_text="String column present in each displayed SQL result that identifies the tenant."
    )
    tenant_value = serializers.CharField(
        max_length=256, trim_whitespace=False, help_text="Exact tenant value bound to the snapshot."
    )
    revoke = serializers.BooleanField(
        default=False, help_text="Revoke embeds for this origin, tenant column and value across all releases."
    )

    def validate_origin(self, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not parsed.netloc.isascii()
            or "*" in parsed.netloc
        ):
            raise serializers.ValidationError("Enter an HTTPS origin without a path, credentials, or wildcard.")
        try:
            port = parsed.port
        except ValueError as exc:
            raise serializers.ValidationError("Enter a valid HTTPS port.") from exc
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        return f"https://{host}:{port}" if port and port != 443 else f"https://{host}"


@require_http_methods(["GET", "POST"])
@never_cache
@csrf_exempt
@xframe_options_exempt
def notebook_app_embed(request: HttpRequest, team_id: int, embed_id: UUID) -> HttpResponse:
    team = get_object_or_404(Team.objects.select_related("organization"), pk=team_id)
    audience = read_embed_audience(team_id, embed_id)
    if audience is None:
        raise Http404()
    issuer = get_object_or_404(User, pk=audience.issued_by_id)
    if not notebook_app_builder_enabled(issuer, team):
        raise Http404()
    if request.method == "POST":
        if request.headers.get("Sec-Fetch-Dest") != "iframe":
            raise Http404()
        output = redeem_signed_embed(team_id, embed_id, request.POST.get("token", ""))
        if output is None:
            raise Http404()
        response = render(
            request,
            "notebooks/app_output.html",
            {
                "title": output.title,
                "description": output.description,
                "revision": output.revision,
                "published_at": output.published_at,
                "tabs": output.tabs,
                "embedded": True,
            },
        )
    else:
        response = render(request, "notebooks/app_embed_frame.html", {"audience": audience.origin})
    nonce = request.csp_nonce
    response["Content-Security-Policy"] = (
        f"default-src 'none'; base-uri 'none'; form-action 'self'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; frame-ancestors {audience.origin}"
    )
    response["Referrer-Policy"] = "no-referrer"
    return response
