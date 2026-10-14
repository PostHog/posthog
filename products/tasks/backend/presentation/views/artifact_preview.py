import re
import json
import hashlib
import secrets
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt

from posthog.csp_middleware import app_frame_ancestor_sources

from products.canvas.backend.artifacts import (
    ARTIFACT_PERMISSIONS_POLICY,
    artifact_delivery_origin,
    require_artifact_host,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.serializers import TASK_RUN_ARTIFACT_MAX_SIZE_BYTES

PREVIEW_TOKEN_TTL_SECONDS = 300


def _cache_key(token: str) -> str:
    return f"task-artifact-preview:{hashlib.sha256(token.encode()).hexdigest()}"


def is_html_artifact(name: str, content_type: str) -> bool:
    mime_type = content_type.split(";", 1)[0].strip().lower()
    return mime_type == "text/html" or name.lower().endswith((".html", ".htm"))


def create_artifact_preview_url(
    *, team_id: int, task_id: str, run_id: str, artifact_id: str, version: int | None = None
) -> str | None:
    if not settings.CANVAS_ARTIFACT_ORIGIN and not (settings.DEBUG or settings.TEST):
        return None
    token = secrets.token_urlsafe(32)
    cache.set(
        _cache_key(token),
        json.dumps([team_id, task_id, run_id, artifact_id, version]),
        timeout=PREVIEW_TOKEN_TTL_SECONDS,
    )
    return f"{artifact_delivery_origin()}/canvas-artifacts/task-preview/{token}/index.html"


def _preview_claims(token: str) -> tuple[int, UUID, UUID, str, int | None]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise Http404
    raw_claims = cache.get(_cache_key(token))
    if not isinstance(raw_claims, str):
        raise Http404
    try:
        team_id, task_id, run_id, artifact_id, version = json.loads(raw_claims)
        if not isinstance(team_id, int) or isinstance(team_id, bool) or not isinstance(artifact_id, str):
            raise ValueError
        if version is not None and (not isinstance(version, int) or isinstance(version, bool) or version < 1):
            raise ValueError
        return team_id, UUID(task_id), UUID(run_id), artifact_id, version
    except (TypeError, ValueError):
        raise Http404 from None


def _task_html_artifact_preview_csp() -> str:
    site = urlsplit(settings.SITE_URL)
    ancestors = dict.fromkeys([f"{site.scheme}://{site.netloc}", *app_frame_ancestor_sources()])
    return "; ".join(
        [
            "sandbox allow-scripts",
            "default-src 'none'",
            "script-src 'unsafe-inline'",
            "style-src 'unsafe-inline'",
            "img-src data: blob:",
            "font-src data:",
            "connect-src 'none'",
            "form-action 'none'",
            "base-uri 'none'",
            "object-src 'none'",
            "frame-src 'none'",
            "worker-src 'none'",
            f"frame-ancestors {' '.join(ancestors)}",
        ]
    )


@xframe_options_exempt
def task_artifact_preview(request: HttpRequest, token: str) -> HttpResponse:
    require_artifact_host(request.get_host())
    team_id, task_id, run_id, artifact_id, version = _preview_claims(token)
    if version is None:
        artifact = tasks_facade.task_run_artifact_entry(run_id, task_id, team_id, artifact_id=artifact_id)
        if artifact is None or not is_html_artifact(
            str(artifact.get("name") or ""), str(artifact.get("content_type") or "")
        ):
            raise Http404
        content, _, error = tasks_facade.read_task_run_artifact(
            run_id, task_id, team_id, storage_path=str(artifact["storage_path"])
        )
    else:
        living_content, error = tasks_facade.read_task_run_living_artifact_version(
            run_id, task_id, team_id, artifact_id=artifact_id, version=version
        )
        if living_content is None or not is_html_artifact(living_content.name, living_content.content_type):
            raise Http404
        content = living_content.content
    if error is not None or content is None or len(content) > TASK_RUN_ARTIFACT_MAX_SIZE_BYTES:
        raise Http404
    response = HttpResponse(content, content_type="text/html; charset=utf-8")
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    response["Content-Security-Policy"] = _task_html_artifact_preview_csp()
    response["Permissions-Policy"] = ARTIFACT_PERMISSIONS_POLICY
    return response
