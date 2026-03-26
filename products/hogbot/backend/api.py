from __future__ import annotations

import fnmatch
import json
from typing import Any
from urllib.parse import urlparse

from django.http import HttpResponse, JsonResponse, StreamingHttpResponse

import requests as http_requests
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ee.hogai.utils.asgi import SyncIterableToAsync

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission
from posthog.settings import SERVER_GATEWAY_INTERFACE

from products.hogbot.backend import gateway, logic

UPSTREAM_COMMAND_TIMEOUT_SECONDS = 600
UPSTREAM_GET_TIMEOUT_SECONDS = 30
ALLOWED_MODAL_SUFFIXES = (".modal.run", ".modal.host")


class SendMessageRequestSerializer(serializers.Serializer):
    content = serializers.CharField()


class SendMessageCompatRequestSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["user_message"])
    content = serializers.CharField()


class ResearchRequestSerializer(serializers.Serializer):
    signal_id = serializers.CharField(max_length=255)
    prompt = serializers.CharField()


class FilesystemPathQuerySerializer(serializers.Serializer):
    path = serializers.CharField(default="/", required=False)


class FilesystemListCompatQuerySerializer(serializers.Serializer):
    glob = serializers.CharField(default="/research/*.md", required=False)


class FilesystemContentQuerySerializer(FilesystemPathQuerySerializer):
    encoding = serializers.ChoiceField(choices=["utf-8", "base64"], default="utf-8", required=False)
    max_bytes = serializers.IntegerField(min_value=1, max_value=5 * 1024 * 1024, default=1024 * 1024, required=False)


class AppendLogRequestSerializer(serializers.Serializer):
    entries = serializers.ListField(child=serializers.JSONField())


class LogQuerySerializer(serializers.Serializer):
    after = serializers.DateTimeField(required=False)
    event_types = serializers.CharField(required=False, allow_blank=True)
    exclude_types = serializers.CharField(required=False, allow_blank=True)
    limit = serializers.IntegerField(min_value=1, max_value=5000, default=1000, required=False)


class HogbotViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "project"
    read_actions = {
        "health",
        "filesystem_stat",
        "filesystem_list",
        "filesystem_content",
        "files",
        "files_read",
        "logs",
        "admin_logs",
        "research_logs",
    }
    write_actions = {
        "send_message",
        "send_message_compat",
        "cancel",
        "research",
        "append_admin_log",
        "append_research_log",
        "register_server",
        "heartbeat_server",
        "unregister_server",
    }

    def _validate_serializer(self, serializer_class, data: dict[str, Any], *, partial: bool = False):
        serializer = serializer_class(data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        action = getattr(view, "action", None)
        if action in self.read_actions:
            return ["project:read"]
        if action in self.write_actions:
            return ["project:write"]
        return None

    @staticmethod
    def _is_valid_sandbox_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"):
            return True

        return bool(
            parsed.scheme == "https" and parsed.hostname and any(parsed.hostname.endswith(suffix) for suffix in ALLOWED_MODAL_SUFFIXES)
        )

    def _coerce_connection(self, connection: gateway.HogbotConnectionInfo | None) -> gateway.HogbotConnectionInfo | Response:
        if not connection or not connection.ready or not connection.server_url:
            return Response({"error": "No active hogbot server for this team"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not self._is_valid_sandbox_url(connection.server_url):
            return Response({"error": "Invalid sandbox URL"}, status=status.HTTP_400_BAD_REQUEST)
        return connection

    def _get_connection(self) -> gateway.HogbotConnectionInfo | Response:
        return self._coerce_connection(gateway.get_hogbot_connection(self.team.pk))

    def _ensure_connection(self, request) -> gateway.HogbotConnectionInfo | Response:
        current = gateway.get_hogbot_connection(self.team.pk)
        if current and current.ready and current.server_url:
            return self._coerce_connection(current)

        try:
            started = gateway.get_or_start_hogbot(
                team_id=self.team.pk,
                user_id=getattr(request.user, "pk", None),
            )
        except Exception as err:
            return Response(
                {"error": f"Failed to start hogbot server: {err}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return self._coerce_connection(started)

    def _proxy_upstream(
        self,
        *,
        connection: gateway.HogbotConnectionInfo,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        stream: bool = False,
        timeout: int,
    ) -> http_requests.Response:
        request_params = dict(params or {})
        if connection.connect_token:
            request_params["_modal_connect_token"] = connection.connect_token

        url = f"{connection.server_url.rstrip('/')}/{path.lstrip('/')}"
        return http_requests.request(
            method=method,
            url=url,
            json=json,
            params=request_params or None,
            stream=stream,
            timeout=timeout,
        )

    def _proxy_json_endpoint(self, request, *, path: str, payload: dict[str, Any], start_if_needed: bool = False) -> Response:
        connection = self._ensure_connection(request) if start_if_needed else self._get_connection()
        if isinstance(connection, Response):
            return connection

        try:
            upstream = self._proxy_upstream(
                connection=connection,
                method="POST",
                path=path,
                json=payload,
                timeout=UPSTREAM_COMMAND_TIMEOUT_SECONDS,
            )
        except http_requests.ConnectionError:
            return Response({"error": "Hogbot server is not reachable"}, status=status.HTTP_502_BAD_GATEWAY)
        except http_requests.Timeout:
            return Response({"error": "Hogbot server request timed out"}, status=status.HTTP_504_GATEWAY_TIMEOUT)

        try:
            data = upstream.json()
        except ValueError:
            data = {"error": f"Hogbot server returned {upstream.status_code}"}
        return Response(data, status=upstream.status_code)

    def _proxy_get_endpoint(self, *, path: str, query_params: dict[str, Any]) -> Response:
        connection = self._get_connection()
        if isinstance(connection, Response):
            return connection

        try:
            upstream = self._proxy_upstream(
                connection=connection,
                method="GET",
                path=path,
                params=query_params,
                timeout=UPSTREAM_GET_TIMEOUT_SECONDS,
            )
        except http_requests.ConnectionError:
            return Response({"error": "Hogbot server is not reachable"}, status=status.HTTP_502_BAD_GATEWAY)
        except http_requests.Timeout:
            return Response({"error": "Hogbot server request timed out"}, status=status.HTTP_504_GATEWAY_TIMEOUT)

        try:
            data = upstream.json()
        except ValueError:
            data = {"error": f"Hogbot server returned {upstream.status_code}"}
        return Response(data, status=upstream.status_code)

    def _read_log_response(self, *, key: str, validated: dict[str, Any]) -> JsonResponse:
        entries, total_count = self._read_log_entries(key=key, validated=validated)
        response = JsonResponse(entries, safe=False)
        response["X-Total-Count"] = str(total_count)
        response["X-Filtered-Count"] = str(len(entries))
        response["Cache-Control"] = "no-cache"
        return response

    def _read_log_entries(self, *, key: str, validated: dict[str, Any]) -> tuple[list[dict], int]:
        event_types = (
            {part.strip() for part in validated["event_types"].split(",") if part.strip()}
            if validated.get("event_types")
            else None
        )
        exclude_types = (
            {part.strip() for part in validated["exclude_types"].split(",") if part.strip()}
            if validated.get("exclude_types")
            else None
        )
        entries, total_count = logic.read_log_entries(
            key,
            after=validated.get("after"),
            event_types=event_types,
            exclude_types=exclude_types,
            limit=validated["limit"],
        )
        return entries, total_count

    def _read_log_text_response(self, *, key: str, validated: dict[str, Any]) -> HttpResponse:
        entries, total_count = self._read_log_entries(key=key, validated=validated)
        body = "\n".join(json.dumps(entry) for entry in entries)
        response = HttpResponse(body, content_type="text/plain; charset=utf-8")
        response["X-Total-Count"] = str(total_count)
        response["X-Filtered-Count"] = str(len(entries))
        response["Cache-Control"] = "no-cache"
        return response

    @action(detail=False, methods=["get"], url_path="health", required_scopes=["project:read"])
    def health(self, request, **kwargs):
        connection = self._get_connection()
        if isinstance(connection, Response):
            return connection

        try:
            upstream = self._proxy_upstream(
                connection=connection,
                method="GET",
                path="/health",
                timeout=UPSTREAM_GET_TIMEOUT_SECONDS,
            )
        except http_requests.ConnectionError:
            return Response({"error": "Hogbot server is not reachable"}, status=status.HTTP_502_BAD_GATEWAY)
        except http_requests.Timeout:
            return Response({"error": "Hogbot server health request timed out"}, status=status.HTTP_504_GATEWAY_TIMEOUT)

        try:
            data = upstream.json()
        except ValueError:
            data = {}
        return Response(data, status=upstream.status_code)

    @action(detail=False, methods=["post"], url_path="send_message", required_scopes=["project:write"])
    def send_message(self, request, **kwargs):
        validated = self._validate_serializer(SendMessageRequestSerializer, request.data)
        return self._proxy_json_endpoint(request, path="/send_message", payload=validated, start_if_needed=True)

    @action(detail=False, methods=["post"], url_path="send-message", required_scopes=["project:write"])
    def send_message_compat(self, request, **kwargs):
        validated = self._validate_serializer(SendMessageCompatRequestSerializer, request.data)
        return self._proxy_json_endpoint(
            request,
            path="/send_message",
            payload={"content": validated["content"]},
            start_if_needed=True,
        )

    @action(detail=False, methods=["post"], url_path="cancel", required_scopes=["project:write"])
    def cancel(self, request, **kwargs):
        return self._proxy_json_endpoint(request, path="/cancel", payload={})

    @action(detail=False, methods=["post"], url_path="research", required_scopes=["project:write"])
    def research(self, request, **kwargs):
        validated = self._validate_serializer(ResearchRequestSerializer, request.data)
        return self._proxy_json_endpoint(request, path="/research", payload=validated, start_if_needed=True)

    @action(detail=False, methods=["get"], url_path="filesystem/stat", required_scopes=["project:read"])
    def filesystem_stat(self, request, **kwargs):
        validated = self._validate_serializer(FilesystemPathQuerySerializer, request.query_params)
        return self._proxy_get_endpoint(path="/filesystem/stat", query_params=validated)

    @action(detail=False, methods=["get"], url_path="filesystem/list", required_scopes=["project:read"])
    def filesystem_list(self, request, **kwargs):
        validated = self._validate_serializer(FilesystemPathQuerySerializer, request.query_params)
        return self._proxy_get_endpoint(path="/filesystem/list", query_params=validated)

    @action(detail=False, methods=["get"], url_path="filesystem/content", required_scopes=["project:read"])
    def filesystem_content(self, request, **kwargs):
        validated = self._validate_serializer(FilesystemContentQuerySerializer, request.query_params)
        return self._proxy_get_endpoint(path="/filesystem/content", query_params=validated)

    @action(detail=False, methods=["get"], url_path="files", required_scopes=["project:read"])
    def files(self, request, **kwargs):
        validated = self._validate_serializer(FilesystemListCompatQuerySerializer, request.query_params)
        pattern = validated["glob"] or "/research/*.md"
        root = pattern.rsplit("/", 1)[0] or "/"
        upstream = self._proxy_get_endpoint(path="/filesystem/list", query_params={"path": root})
        if upstream.status_code != status.HTTP_200_OK:
            return upstream

        entries = upstream.data.get("entries", []) if isinstance(upstream.data, dict) else []
        results = [
            {
                "path": entry["path"],
                "filename": entry["name"],
                "size": entry["size"],
                "modified_at": entry.get("mtime_ms"),
            }
            for entry in entries
            if entry.get("type") == "file" and fnmatch.fnmatch(entry.get("path", ""), pattern)
        ]
        results.sort(key=lambda entry: entry["path"])
        return Response({"results": results})

    @action(detail=False, methods=["get"], url_path="files/read", required_scopes=["project:read"])
    def files_read(self, request, **kwargs):
        validated = self._validate_serializer(FilesystemPathQuerySerializer, request.query_params)
        upstream = self._proxy_get_endpoint(
            path="/filesystem/content",
            query_params={
                "path": validated["path"],
                "encoding": "utf-8",
                "max_bytes": 1024 * 1024,
            },
        )
        if upstream.status_code != status.HTTP_200_OK:
            error = upstream.data.get("error") if isinstance(upstream.data, dict) else "File read failed"
            return HttpResponse(error, status=upstream.status_code, content_type="text/plain")

        content = upstream.data.get("content", "") if isinstance(upstream.data, dict) else ""
        return HttpResponse(content, content_type="text/plain; charset=utf-8")

    @action(detail=False, methods=["get"], url_path="logs", required_scopes=["project:read"])
    def logs(self, request, **kwargs):
        connection = self._get_connection()
        if isinstance(connection, Response):
            return connection

        try:
            upstream = self._proxy_upstream(
                connection=connection,
                method="GET",
                path="/logs",
                params=request.query_params.dict(),
                stream=True,
                timeout=UPSTREAM_COMMAND_TIMEOUT_SECONDS,
            )
        except http_requests.ConnectionError:
            return Response({"error": "Hogbot server is not reachable"}, status=status.HTTP_502_BAD_GATEWAY)
        except http_requests.Timeout:
            return Response({"error": "Hogbot server stream timed out"}, status=status.HTTP_504_GATEWAY_TIMEOUT)

        if upstream.status_code >= 400:
            try:
                data = upstream.json()
            except ValueError:
                data = {"error": f"Hogbot server returned {upstream.status_code}"}
            upstream.close()
            return Response(data, status=upstream.status_code)

        def stream_chunks():
            try:
                yield from upstream.iter_content(chunk_size=4096)
            finally:
                upstream.close()

        content = SyncIterableToAsync(stream_chunks()) if SERVER_GATEWAY_INTERFACE == "ASGI" else stream_chunks()
        response = StreamingHttpResponse(content, content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @action(detail=False, methods=["get"], url_path="admin/logs", required_scopes=["project:read"])
    def admin_logs(self, request, **kwargs):
        validated = self._validate_serializer(LogQuerySerializer, request.query_params)
        return self._read_log_text_response(key=logic.get_admin_log_key(self.team.pk), validated=validated)

    @action(detail=False, methods=["post"], url_path="admin/append_log", required_scopes=["project:write"])
    def append_admin_log(self, request, **kwargs):
        validated = self._validate_serializer(AppendLogRequestSerializer, request.data)
        logic.append_log_entries(logic.get_admin_log_key(self.team.pk), self.team.pk, validated["entries"])
        return Response({"ok": True})

    @action(detail=False, methods=["get"], url_path=r"research/(?P<signal_id>[^/.]+)/logs", required_scopes=["project:read"])
    def research_logs(self, request, signal_id: str | None = None, **kwargs):
        validated = self._validate_serializer(LogQuerySerializer, request.query_params)
        assert signal_id is not None
        return self._read_log_response(key=logic.get_research_log_key(self.team.pk, signal_id), validated=validated)

    @action(detail=False, methods=["post"], url_path=r"research/(?P<signal_id>[^/.]+)/append_log", required_scopes=["project:write"])
    def append_research_log(self, request, signal_id: str | None = None, **kwargs):
        validated = self._validate_serializer(AppendLogRequestSerializer, request.data)
        assert signal_id is not None
        logic.append_log_entries(logic.get_research_log_key(self.team.pk, signal_id), self.team.pk, validated["entries"])
        return Response({"ok": True})

    @action(detail=False, methods=["post"], url_path="server/register", required_scopes=["project:write"])
    def register_server(self, request, **kwargs):
        return Response({"ok": True, "deprecated": True})

    @action(detail=False, methods=["post"], url_path="server/heartbeat", required_scopes=["project:write"])
    def heartbeat_server(self, request, **kwargs):
        return Response({"ok": True, "deprecated": True})

    @action(detail=False, methods=["post"], url_path="server/unregister", required_scopes=["project:write"])
    def unregister_server(self, request, **kwargs):
        return Response({"ok": True, "deprecated": True})
