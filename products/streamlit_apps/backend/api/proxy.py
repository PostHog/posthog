from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.views import View

import requests as http_requests

from posthog.models import Team

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox
from products.streamlit_apps.backend.services.app_runtime import AppRuntimeService

logger = logging.getLogger(__name__)

PROXY_TIMEOUT_SECONDS = 30
FORWARDED_HEADERS = {
    "accept",
    "accept-encoding",
    "accept-language",
    "content-type",
    "content-length",
    "cache-control",
    "pragma",
    "referer",
    "x-requested-with",
}


class StreamlitProxyView(View):
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def dispatch(self, request: HttpRequest, team_id: int, short_id: str, path: str = "") -> HttpResponse:
        user = self._authenticate(request)
        if user is None:
            return HttpResponse("Authentication required.", status=401)

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return HttpResponse("Team not found.", status=404)

        if not team.all_users_with_access().filter(id=user.id).exists():
            return HttpResponse("Not a member of this team.", status=403)

        try:
            app = StreamlitApp.objects.get(team=team, short_id=short_id, deleted=False)
        except StreamlitApp.DoesNotExist:
            return HttpResponse("App not found.", status=404)

        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        if not sandbox_record or sandbox_record.status != StreamlitAppSandbox.Status.RUNNING:
            return HttpResponse("App is not running.", status=503)

        if sandbox_record.current_viewers >= sandbox_record.max_viewers:
            return HttpResponse("App is busy, please try again later.", status=503)

        runtime = AppRuntimeService()
        tunnel_url = runtime.get_tunnel_url(app)
        if not tunnel_url:
            return HttpResponse("Unable to connect to app.", status=502)

        token = runtime.get_connect_token(app, user_id=user.id, team_id=team.id)

        sandbox_record.last_activity_at = timezone.now()
        sandbox_record.save(update_fields=["last_activity_at"])

        return self._forward_request(request, tunnel_url, path, token)

    def _authenticate(self, request: HttpRequest):
        if hasattr(request, "user") and request.user.is_authenticated:
            return request.user
        return None

    def _forward_request(
        self,
        request: HttpRequest,
        tunnel_url: str,
        path: str,
        token: str | None,
    ) -> HttpResponse:
        target_url = f"{tunnel_url.rstrip('/')}/{path}"
        if request.META.get("QUERY_STRING"):
            target_url = f"{target_url}?{request.META['QUERY_STRING']}"

        headers = {}
        for header_name in FORWARDED_HEADERS:
            django_key = f"HTTP_{header_name.upper().replace('-', '_')}"
            if header_name == "content-type":
                django_key = "CONTENT_TYPE"
            elif header_name == "content-length":
                django_key = "CONTENT_LENGTH"
            value = request.META.get(django_key)
            if value:
                headers[header_name] = value

        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            upstream_response = http_requests.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=request.body if request.method in ("POST", "PUT", "PATCH") else None,
                timeout=PROXY_TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=False,
            )
        except http_requests.Timeout:
            return HttpResponse("App request timed out.", status=504)
        except http_requests.ConnectionError:
            return HttpResponse("Unable to connect to app.", status=502)

        response = HttpResponse(
            content=upstream_response.content,
            status=upstream_response.status_code,
        )

        passthrough_headers = {"content-type", "content-encoding", "cache-control", "etag", "last-modified"}
        for header_name in passthrough_headers:
            value = upstream_response.headers.get(header_name)
            if value:
                response[header_name] = value

        return response
