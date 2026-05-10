"""
Unauthenticated public endpoints for visual_review.

Currently exposes a redirect-to-S3 endpoint keyed by Artifact UUID,
used to embed images inside GitHub PR comments. Artifacts are
content-addressed and UUIDs carry 122 bits of entropy — unguessability
is the security model. GitHub's image proxy (camo) caches the bytes on
first fetch, so this endpoint typically serves a given URL once.
"""

from __future__ import annotations

from uuid import UUID

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

import structlog

from ..models import Artifact
from ..storage import ArtifactStorage

logger = structlog.get_logger(__name__)

_ARTIFACT_CACHE_MAX_AGE = 24 * 60 * 60  # 24h
_PRESIGNED_EXPIRATION = 60 * 60  # 1h — long enough for a single camo fetch


@require_GET
@cache_control(public=True, max_age=_ARTIFACT_CACHE_MAX_AGE, immutable=True)
def public_artifact_view(request: HttpRequest, artifact_id: UUID) -> HttpResponse:
    """Redirect to a fresh presigned S3 URL for the artifact.

    Returns 404 if the artifact does not exist or storage is disabled.
    """
    try:
        # Cross-team lookup: this endpoint is intentionally unauthenticated and
        # keyed only by the artifact's unguessable UUID — no team context exists.
        artifact = Artifact.objects.unscoped().only("id", "repo_id", "content_hash").get(id=artifact_id)
    except Artifact.DoesNotExist:
        return HttpResponseNotFound()

    storage = ArtifactStorage(repo_id=str(artifact.repo_id))
    presigned_url = storage.get_presigned_download_url(artifact.content_hash, expiration=_PRESIGNED_EXPIRATION)
    if not presigned_url:
        logger.warning("visual_review.public_artifact_no_url", artifact_id=str(artifact_id))
        return HttpResponseNotFound()

    response = HttpResponseRedirect(presigned_url)
    patch_cache_control(response, public=True, max_age=_ARTIFACT_CACHE_MAX_AGE, immutable=True)
    return response
