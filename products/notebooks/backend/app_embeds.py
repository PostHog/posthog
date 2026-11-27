import json
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from rest_framework.exceptions import APIException, PermissionDenied, Throttled, ValidationError

from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.notebooks.backend.app_output_projection import app_output_tabs
from products.notebooks.backend.facade.contracts import AppEmbedAudience, AppOutput, AppOutputTab, AppViewGrantResult
from products.notebooks.backend.models import Notebook, NotebookAppEmbed, NotebookAppRelease

ISSUER = "posthog:notebook-app-embed"
MAX_PROJECT_AUDIENCES = 100
ISSUE_BUDGET = Budget(burst=10, per_hour=60)
VERIFIED_VIEW_BUDGET = Budget(burst=300, per_hour=6000)


class EmbedCapacityUnavailable(APIException):
    status_code = 503
    default_detail = "Embed capacity is temporarily unavailable. Try again shortly."
    wait = 5


def require_capacity(key: str, budget: Budget) -> None:
    admission = consume(key, budget)
    if isinstance(admission, BucketUnavailable):
        raise EmbedCapacityUnavailable()
    if isinstance(admission, BucketDecision) and not admission.allowed:
        raise Throttled(wait=admission.retry_after)


@transaction.atomic
def change_signed_embed(
    team_id: int,
    notebook_id: UUID,
    issuer_id: int,
    origin: str,
    tenant_column: str,
    tenant_value: str,
    revoke: bool,
    revision: int | None = None,
) -> AppViewGrantResult:
    notebook = (
        Notebook.objects.select_for_update(of=("self",))
        .select_related("team__organization")
        .get(pk=notebook_id, team_id=team_id, deleted=False)
    )
    audience = {"origin": origin, "tenant_column": tenant_column, "tenant_value": tenant_value}
    if revoke:
        NotebookAppEmbed.objects.for_team(team_id).filter(release__notebook=notebook, **audience).delete()
        return AppViewGrantResult(url=None, expires_at=None)
    if not notebook.team.organization.allow_publicly_shared_resources:
        raise PermissionDenied("Public sharing is disabled for this organization.")
    require_capacity(f"notebooks:embed:issue:{team_id}", ISSUE_BUDGET)
    release = (
        NotebookAppRelease.objects.for_team(team_id)
        .filter(notebook=notebook)
        .defer("variables")
        .order_by("-revision")
        .first()
    )
    if release is None or notebook.app_published is None:
        raise ValidationError("Publish the app before creating an embed.")
    if release.revision != revision:
        raise ValidationError({"revision": "Open the latest published release before creating an embed."})
    tabs = app_output_tabs(release, tenant_column=tenant_column, tenant_value=tenant_value)
    if not any("columns" in block for tab in tabs for block in tab.blocks):
        raise ValidationError("Add a published SQL result with a tenant column and a visible data column.")
    snapshot = [asdict(tab) for tab in tabs]
    if len(json.dumps(snapshot).encode()) > 1024 * 1024:
        raise ValidationError("Reduce the saved result size before creating an embed.")
    expires_at = timezone.now() + timedelta(hours=24)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"notebooks:embed-capacity:{team_id}"])
    existing = NotebookAppEmbed.objects.for_team(team_id).filter(expires_at__gt=timezone.now())
    if existing.count() >= MAX_PROJECT_AUDIENCES and not existing.filter(release=release, **audience).exists():
        raise ValidationError(
            "This project has reached its embed audience limit. Revoke an existing embed and try again."
        )
    private_key = Ed25519PrivateKey.generate()
    embed, _ = NotebookAppEmbed.objects.for_team(team_id).update_or_create(
        team_id=team_id,
        release=release,
        origin=origin,
        tenant_column=tenant_column,
        tenant_value=tenant_value,
        defaults={
            "issued_by_id": issuer_id,
            "verification_key": private_key.public_key().public_bytes_raw(),
            "expires_at": expires_at,
            "snapshot": snapshot,
        },
    )
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": origin,
            "sub": str(embed.pk),
            "exp": expires_at,
            "project": team_id,
            "release": str(release.pk),
            "tenant": sha256(tenant_value.encode()).hexdigest(),
        },
        private_key,
        algorithm="EdDSA",
    )
    return AppViewGrantResult(
        url=reverse("notebook_app_embed", args=[team_id, embed.pk]) + "#" + token, expires_at=expires_at
    )


def _active_embed(team_id: int, embed_id: UUID) -> NotebookAppEmbed | None:
    embed = (
        NotebookAppEmbed.objects.for_team(team_id)
        .filter(
            pk=embed_id,
            team_id=team_id,
            expires_at__gt=timezone.now(),
            release__team_id=team_id,
            release__notebook__team_id=team_id,
            release__notebook__deleted=False,
            release__notebook__app_published__isnull=False,
            issued_by__is_active=True,
            team__organization__is_active=True,
            team__organization__is_pending_deletion=False,
            team__organization__allow_publicly_shared_resources=True,
        )
        .select_related("issued_by", "team__organization", "release")
        .defer("snapshot", "release__sql_rows", "release__markdown", "release__variables")
        .first()
    )
    if embed is None or not authorization.check(
        resource=Resource(type=ResourceType.ORGANIZATION, id=str(embed.team.organization_id)),
        action=Action.SHARE,
        subject=Subject(user_id=embed.issued_by_id),
    ):
        return None
    return embed


def read_embed_audience(team_id: int, embed_id: UUID) -> AppEmbedAudience | None:
    embed = _active_embed(team_id, embed_id)
    return AppEmbedAudience(origin=embed.origin, issued_by_id=embed.issued_by_id) if embed else None


def redeem_signed_embed(team_id: int, embed_id: UUID, token: str) -> AppOutput | None:
    embed = _active_embed(team_id, embed_id)
    if embed is None or len(token) > 4096:
        return None
    try:
        claims = jwt.decode(
            token,
            Ed25519PublicKey.from_public_bytes(bytes(embed.verification_key)),
            algorithms=["EdDSA"],
            audience=embed.origin,
            issuer=ISSUER,
            subject=str(embed.pk),
            options={"require": ["iss", "aud", "sub", "exp", "project", "release", "tenant"]},
        )
    except jwt.InvalidTokenError:
        return None
    if (
        claims["project"] != team_id
        or claims["release"] != str(embed.release_id)
        or claims["tenant"] not in (sha256(embed.tenant_value.encode()).hexdigest(), embed.tenant_value)
    ):
        return None
    require_capacity(f"notebooks:embed:verified:{embed_id}", VERIFIED_VIEW_BUDGET)
    return AppOutput(
        title=embed.release.layout.get("title") or embed.release.title,
        description=embed.release.layout.get("description"),
        revision=embed.release.revision,
        published_at=embed.release.published_at,
        tabs=[AppOutputTab(**tab) for tab in embed.snapshot],
    )
