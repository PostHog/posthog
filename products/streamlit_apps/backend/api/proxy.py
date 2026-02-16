from __future__ import annotations

import re
import logging

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests as http_requests

from posthog.models import Team

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox
from products.streamlit_apps.backend.services.app_runtime import AppRuntimeService

logger = logging.getLogger(__name__)

PROXY_TIMEOUT_SECONDS = 30
CONNECT_URL_CACHE_TTL = 180  # 3 minutes

# Don't forward accept-encoding — we need uncompressed HTML to inject the WS redirect script
FORWARDED_HEADERS = {
    "accept",
    "accept-language",
    "content-type",
    "content-length",
    "cache-control",
    "pragma",
    "x-requested-with",
}

WS_REDIRECT_SCRIPT = """<script>(function(){var O=window.WebSocket;var b="%s";var t="%s";window.WebSocket=function(url,p){var u=new URL(url,location.href);var i=u.pathname.indexOf('_stcore/stream');if(i!==-1){var w=b.replace('https://','wss://').replace('http://','ws://');w+='/'+u.pathname.substring(i)+'?_modal_connect_token='+t;return new O(w,p);}return new O(url,p);};window.WebSocket.prototype=O.prototype;window.WebSocket.CONNECTING=O.CONNECTING;window.WebSocket.OPEN=O.OPEN;window.WebSocket.CLOSING=O.CLOSING;window.WebSocket.CLOSED=O.CLOSED;})()</script>"""


def _get_cached_connect_url(app: StreamlitApp, user_id: int, team_id: int) -> dict | None:
    cache_key = f"streamlit_connect_url:{app.id}:{user_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    runtime = AppRuntimeService()
    result = runtime.get_connect_url(app, user_id=user_id, team_id=team_id)
    if result:
        cache.set(cache_key, result, CONNECT_URL_CACHE_TTL)
    return result


def _invalidate_connect_url(app: StreamlitApp, user_id: int) -> None:
    cache_key = f"streamlit_connect_url:{app.id}:{user_id}"
    cache.delete(cache_key)


def _inject_ws_redirect(content: bytes, content_type: str, modal_url: str, token: str) -> bytes:
    if "text/html" not in content_type:
        return content

    import json

    html = content.decode("utf-8", errors="replace")
    safe_url = json.dumps(modal_url)[1:-1]
    safe_token = json.dumps(token)[1:-1]
    script_tag = WS_REDIRECT_SCRIPT % (safe_url, safe_token)
    html = re.sub(r"(<head[^>]*>)", r"\1" + script_tag, html, count=1, flags=re.IGNORECASE)
    return html.encode("utf-8")


@method_decorator(csrf_exempt, name="dispatch")
class StreamlitProxyView(View):
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def dispatch(self, request: HttpRequest, team_id: int, short_id: str, path: str = "") -> HttpResponse:
        user_id = self._authenticate(request, team_id=int(team_id), short_id=short_id)
        if user_id is None:
            return HttpResponse("Authentication required.", status=401)

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return HttpResponse("Team not found.", status=404)

        if not team.all_users_with_access().filter(id=user_id).exists():
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

        connect_info = _get_cached_connect_url(app, user_id=user_id, team_id=team.id)
        if not connect_info:
            return HttpResponse("Unable to connect to app.", status=502)

        sandbox_record.last_activity_at = timezone.now()
        sandbox_record.save(update_fields=["last_activity_at"])

        return self._forward_request(
            request, connect_info["url"], path, connect_info["token"], app=app, user_id=user_id
        )

    def _authenticate(self, request: HttpRequest, team_id: int, short_id: str) -> int | None:
        proxy_token = request.GET.get("_proxy_token")
        if proxy_token:
            try:
                from products.streamlit_apps.backend.services.bridge import validate_proxy_token

                claims = validate_proxy_token(proxy_token)
                if claims.team_id == team_id and claims.app_short_id == short_id:
                    return claims.user_id
            except Exception:
                pass

        if hasattr(request, "user") and request.user.is_authenticated:
            return request.user.id
        return None

    def _forward_request(
        self,
        request: HttpRequest,
        base_url: str,
        path: str,
        token: str,
        app: StreamlitApp | None = None,
        user_id: int | None = None,
    ) -> HttpResponse:
        target_url = f"{base_url.rstrip('/')}/{path}"

        # Build query string: strip _proxy_token (auth-only), inject _modal_connect_token
        raw_qs = request.META.get("QUERY_STRING", "")
        qs_parts = [p for p in raw_qs.split("&") if p and not p.startswith("_proxy_token=")]
        qs_parts.append(f"_modal_connect_token={token}")
        target_url = f"{target_url}?{'&'.join(qs_parts)}"

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
        except (http_requests.Timeout, http_requests.ConnectionError) as exc:
            if app and user_id:
                _invalidate_connect_url(app, user_id)
                StreamlitAppSandbox.objects.filter(app=app, status=StreamlitAppSandbox.Status.RUNNING).update(
                    status=StreamlitAppSandbox.Status.STOPPED
                )
            is_timeout = isinstance(exc, http_requests.Timeout)
            logger.warning(
                "Streamlit proxy %s for app %s",
                "timeout" if is_timeout else "connection error",
                app.id if app else "unknown",
            )
            return HttpResponse(
                "App request timed out." if is_timeout else "Unable to connect to app.",
                status=504 if is_timeout else 502,
            )

        content_type = upstream_response.headers.get("content-type", "")
        body = _inject_ws_redirect(upstream_response.content, content_type, base_url, token)

        response = HttpResponse(
            content=body,
            status=upstream_response.status_code,
        )

        passthrough_headers = {"content-type", "cache-control", "etag", "last-modified"}
        for header_name in passthrough_headers:
            value = upstream_response.headers.get(header_name)
            if value:
                response[header_name] = value

        # TODO: re-enable CSP once WebSocket connectivity is confirmed working
        # response["Content-Security-Policy"] = PROXY_CSP
        return response
