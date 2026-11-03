import re
import json
import hashlib
import secrets
from collections.abc import AsyncIterator
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.cache import caches
from django.http import Http404, HttpRequest, StreamingHttpResponse
from django.utils.connection import ConnectionProxy
from django.views.decorators.clickjacking import xframe_options_exempt

from posthog.api.streaming import streaming_response
from posthog.csp_middleware import app_frame_ancestor_sources
from posthog.dataclasses import frozen

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.serializers import TASK_RUN_ARTIFACT_MAX_SIZE_BYTES

PREVIEW_TOKEN_TTL_SECONDS = 300

cache = ConnectionProxy(caches, "task_artifact_preview")


def _cache_key(token: str) -> str:
    return f"task-artifact-preview:{hashlib.sha256(token.encode()).hexdigest()}"


def create_artifact_preview_url(
    *,
    team_id: int,
    task_id: str,
    run_id: str,
    artifact_id: str,
    version: int | None = None,
    script_digest: str | None = None,
) -> str | None:
    if not settings.CANVAS_ARTIFACT_ORIGIN and not (settings.DEBUG or settings.TEST):
        return None
    token = secrets.token_urlsafe(32)
    cache.set(
        _cache_key(token),
        json.dumps([team_id, task_id, run_id, artifact_id, version, script_digest]),
        timeout=PREVIEW_TOKEN_TTL_SECONDS,
    )
    from products.canvas.backend.facade.api import artifact_delivery_origin

    return f"{artifact_delivery_origin()}/canvas-artifacts/task-preview/{token}/index.html"


@frozen
class _PreviewClaims:
    team_id: int
    task_id: UUID
    run_id: UUID
    artifact_id: str
    version: int | None
    script_digest: str | None


def _preview_claims(token: str) -> _PreviewClaims:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise Http404
    raw_claims = cache.get(_cache_key(token))
    if not isinstance(raw_claims, str):
        raise Http404
    try:
        team_id, task_id, run_id, artifact_id, version, script_digest = json.loads(raw_claims)
        if (
            not isinstance(team_id, int)
            or isinstance(team_id, bool)
            or not isinstance(artifact_id, str)
            or not (script_digest is None or isinstance(script_digest, str))
        ):
            raise ValueError
        if version is not None and (not isinstance(version, int) or isinstance(version, bool) or version < 1):
            raise ValueError
        return _PreviewClaims(
            team_id=team_id,
            task_id=UUID(task_id),
            run_id=UUID(run_id),
            artifact_id=artifact_id,
            version=version,
            script_digest=script_digest,
        )
    except (TypeError, ValueError):
        raise Http404 from None


def _task_html_artifact_preview_csp(*, scripts: bool) -> str:
    site = urlsplit(settings.SITE_URL)
    ancestors = dict.fromkeys([f"{site.scheme}://{site.netloc}", *app_frame_ancestor_sources()])
    return "; ".join(
        [
            "sandbox allow-scripts" if scripts else "sandbox",
            "default-src 'none'",
            "script-src 'unsafe-inline'" if scripts else "script-src 'none'",
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


SHIM_CHUNK_BYTES = 1024 * 1024
_HTML_ATTRIBUTE_ESCAPES = ((b"&", b"&amp;"), (b"<", b"&lt;"), (b">", b"&gt;"), (b'"', b"&quot;"), (b"'", b"&#x27;"))


_NETWORK_HINT_TAGS = re.compile(rb"<(link|meta)(?=[\t\n\f\r />])", re.IGNORECASE)
_DNS_PREFETCH_OFF = b'<meta http-equiv="x-dns-prefetch-control" content="off">'


def _leading_doctype_end(content: bytes) -> int:
    position = 3 if content.startswith(b"\xef\xbb\xbf") else 0
    while True:
        while position < len(content) and content[position : position + 1].isspace():
            position += 1
        if not content.startswith(b"<!--", position):
            break
        comment_end = content.find(b"-->", position + 4)
        if comment_end == -1:
            return 0
        position = comment_end + 3
    if content[position : position + 9].lower() != b"<!doctype":
        return 0
    doctype_end = content.find(b">", position)
    return doctype_end + 1 if doctype_end != -1 else 0


def _without_network_hints(content: bytes) -> bytes:
    content = _NETWORK_HINT_TAGS.sub(rb"<x-\1", content)
    split = _leading_doctype_end(content)
    return content[:split] + _DNS_PREFETCH_OFF + content[split:]


def _escape_html_attribute(chunk: bytes) -> bytes:
    for raw, entity in _HTML_ATTRIBUTE_ESCAPES:
        chunk = chunk.replace(raw, entity)
    return chunk


async def _task_html_artifact_shim(content: bytes, *, scripts: bool) -> AsyncIterator[bytes]:
    yield (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        "<style>html,body{margin:0;height:100%}iframe{display:block;width:100%;height:100%;border:0}</style>"
        f'</head><body><iframe sandbox="{"allow-scripts" if scripts else ""}" title="Artifact" srcdoc="'
    ).encode()
    for start in range(0, len(content), SHIM_CHUNK_BYTES):
        yield _escape_html_attribute(content[start : start + SHIM_CHUNK_BYTES])
    yield b'"></iframe></body></html>'


@xframe_options_exempt
def task_artifact_preview(request: HttpRequest, token: str) -> StreamingHttpResponse:
    from products.canvas.backend.facade.api import ARTIFACT_PERMISSIONS_POLICY, require_artifact_host

    require_artifact_host(request.get_host())
    claims = _preview_claims(token)
    if claims.version is None:
        content = tasks_facade.read_task_run_html_artifact(
            claims.run_id, claims.task_id, claims.team_id, artifact_id=claims.artifact_id
        )
        error = None
    else:
        living_content, error = tasks_facade.read_task_run_living_artifact_version(
            claims.run_id, claims.task_id, claims.team_id, artifact_id=claims.artifact_id, version=claims.version
        )
        if living_content is None or not tasks_facade.is_html_artifact(
            living_content.name, living_content.content_type
        ):
            raise Http404
        content = living_content.content
    if error is not None or content is None or len(content) > TASK_RUN_ARTIFACT_MAX_SIZE_BYTES:
        raise Http404
    scripts = claims.script_digest is not None and hashlib.sha256(content).hexdigest() == claims.script_digest
    response = streaming_response(
        _task_html_artifact_shim(content if scripts else _without_network_hints(content), scripts=scripts),
        content_type="text/html; charset=utf-8",
    )
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    response["Content-Security-Policy"] = _task_html_artifact_preview_csp(scripts=scripts)
    response["Permissions-Policy"] = ARTIFACT_PERMISSIONS_POLICY
    return response
