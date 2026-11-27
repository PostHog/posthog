from urllib.parse import urlsplit
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from rest_framework import serializers

from posthog.models import Team, User
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume
from posthog.utils import get_trusted_client_ip

from products.notebooks.backend.facade.app_embeds import read_embed_audience, redeem_signed_embed
from products.notebooks.backend.presentation.app_serializers import notebook_app_builder_enabled

PUBLIC_IP_BUDGET = Budget(burst=120, per_hour=1200)
PUBLIC_EMBED_BUDGET = Budget(burst=300, per_hour=6000)


def public_embed_rate_limit(key: str, budget: Budget) -> HttpResponse | None:
    decision = consume(key, budget)
    if isinstance(decision, BucketUnavailable):
        return HttpResponse(status=503, headers={"Retry-After": "5"})
    if isinstance(decision, BucketDecision) and not decision.allowed:
        return HttpResponse(status=429, headers={"Retry-After": str(decision.retry_after)})
    return None


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
        if ":" in parsed.hostname:
            raise serializers.ValidationError(
                "Use a hostname for the site origin. Browsers cannot frame this embed from an IPv6 address."
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise serializers.ValidationError("Enter a valid HTTPS port.") from exc
        host = parsed.hostname
        return f"https://{host}:{port}" if port and port != 443 else f"https://{host}"


@require_http_methods(["GET", "POST"])
@never_cache
@csrf_exempt
@xframe_options_exempt
def notebook_app_embed(request: HttpRequest, team_id: int, embed_id: UUID) -> HttpResponse:
    from django.template.response import TemplateResponse

    if limited := public_embed_rate_limit(
        f"notebooks:embed:ip:{get_trusted_client_ip(request) or 'unknown'}", PUBLIC_IP_BUDGET
    ):
        return limited
    team = get_object_or_404(Team.objects.select_related("organization"), pk=team_id)
    audience = read_embed_audience(team_id, embed_id)
    if audience is None:
        raise Http404()
    if limited := public_embed_rate_limit(f"notebooks:embed:view:{embed_id}", PUBLIC_EMBED_BUDGET):
        return limited
    issuer = get_object_or_404(User, pk=audience.issued_by_id)
    if not notebook_app_builder_enabled(issuer, team):
        raise Http404()
    if request.method == "POST":
        if request.headers.get("Sec-Fetch-Dest") != "iframe":
            raise Http404()
        output = redeem_signed_embed(team_id, embed_id, request.POST.get("token", ""))
        if output is None:
            raise Http404()
        response = TemplateResponse(
            request,
            "notebooks/app_embed_output.html",
            {
                "title": output.title,
                "description": output.description,
                "revision": output.revision,
                "published_at": output.published_at,
                "tabs": output.tabs,
                "embedded": True,
                "audience": audience.origin,
            },
        )
    else:
        response = TemplateResponse(request, "notebooks/app_embed_frame.html", {"audience": audience.origin})
    response["Referrer-Policy"] = "no-referrer"
    return response
