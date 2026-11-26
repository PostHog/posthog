import json
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from rest_framework.exceptions import PermissionDenied, ValidationError

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.notebooks.backend.app_delivery import app_output_tabs
from products.notebooks.backend.facade.contracts import AppEmbedAudience, AppOutput, AppOutputTab, AppViewGrantResult
from products.notebooks.backend.models import Notebook, NotebookAppEmbed, NotebookAppRelease

ISSUER = "posthog:notebook-app-embed"


@transaction.atomic
def change_signed_embed(
    team_id: int, notebook_id: UUID, issuer_id: int, origin: str, tenant_column: str, tenant_value: str, revoke: bool
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
    release = (
        NotebookAppRelease.objects.for_team(team_id)
        .filter(notebook=notebook)
        .defer("sql_rows", "variables")
        .order_by("-revision")
        .first()
    )
    if release is None or notebook.app_published is None:
        raise ValidationError("Publish the app before creating an embed.")
    tabs = app_output_tabs(release, tenant_column=tenant_column, tenant_value=tenant_value)
    if not any("columns" in block for tab in tabs for block in tab.blocks):
        raise ValidationError("Add a published SQL result with a tenant column and a visible data column.")
    snapshot = [asdict(tab) for tab in tabs]
    if len(json.dumps(snapshot).encode()) > 1024 * 1024:
        raise ValidationError("Reduce the saved result size before creating an embed.")
    expires_at = timezone.now() + timedelta(hours=24)
    private_key = Ed25519PrivateKey.generate()
    embed, _ = NotebookAppEmbed.objects.for_team(team_id).update_or_create(
        team_id=team_id,
        release=release,
        **audience,
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
            "tenant": tenant_value,
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
        or claims["tenant"] != embed.tenant_value
    ):
        return None
    return AppOutput(
        title=embed.release.layout.get("title") or embed.release.title,
        description=embed.release.layout.get("description"),
        revision=embed.release.revision,
        published_at=embed.release.published_at,
        tabs=[AppOutputTab(**tab) for tab in embed.snapshot],
    )
