"""Serializers and endpoints for stored credentials."""

from __future__ import annotations

import dataclasses
from typing import Any, cast
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action
from posthog.models.user import User

from products.warehouse_sources.backend.facade.models import PendingSourceCredential
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

from . import viewset


class SourceConnectLinkSerializer(serializers.Serializer):
    source_type = serializers.CharField(help_text="The source type the link is for.")
    auth_method = serializers.ChoiceField(
        choices=["oauth", "credentials"],
        help_text=(
            "What the user will do on the connect page: 'oauth' = authorize an account in their browser; "
            "'credentials' = enter connection details (or pick OAuth where the source offers both). Either "
            "way secrets never pass through the agent, and the result is always a stored credential id."
        ),
    )
    connect_url = serializers.CharField(
        help_text=(
            "Full URL to share with the user. It opens the source's connection form in PostHog — "
            "credentials never pass through the agent or the chat."
        )
    )
    instructions = serializers.CharField(help_text="Next steps for the agent to relay to the user.")


class SourceCredentialCreateSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type these credentials are for (e.g. 'Stripe', 'Postgres').",
    )
    payload = serializers.DictField(
        help_text=(
            "Connection details as flat keys for the source_type — the same fields the create flow accepts "
            "(host, port, password, API key, …). Checked against a live connection before being stored."
        ),
    )


class SourceCredentialSerializer(serializers.Serializer):
    credential_id = serializers.UUIDField(
        help_text="Stored credential id. Pass to the setup endpoint as {'credential_id': <id>} to create the source."
    )
    source_type = serializers.CharField(help_text="The source type the stored credentials are for.")
    created_at = serializers.DateTimeField(help_text="When the credentials were stored.")
    expires_at = serializers.DateTimeField(
        help_text="When the stored credentials expire. Unconsumed credentials are unusable past this time."
    )


def _find_unresolved_secret_refs(payload: Any) -> list[str]:
    """Return payload keys whose value is an unresolved secret reference.

    The wizard CLI's `wizard_ask` returns sensitive answers as `{"secretRef": "..."}` objects that the
    caller must resolve to real values before they reach PostHog. If one slips through, source creation
    fails downstream with a confusing "invalid credentials"/"invalid API key" error — detect it up front
    so the agent gets an actionable message instead.
    """
    if not isinstance(payload, dict):
        return []
    return [key for key, value in payload.items() if isinstance(value, dict) and "secretRef" in value]


def _unresolved_secret_ref_response(payload: Any) -> Response | None:
    offenders = _find_unresolved_secret_refs(payload)
    if not offenders:
        return None
    return Response(
        status=status.HTTP_400_BAD_REQUEST,
        data={
            "message": (
                f"Unresolved secret reference(s) for: {', '.join(sorted(offenders))}. These fields are still "
                "`{'secretRef': ...}` objects — PostHog cannot resolve them. Resolve the secret to its real "
                "value before calling (or collect credentials via data-warehouse-source-connect-link and pass "
                "the resulting credential_id instead)."
            )
        },
    )


def _find_top_level_oauth_field(config: dict) -> dict | None:
    """Find a top-level OAuth field ({type: 'oauth', kind, name, ...}) in a source config dump.

    Only a top-level OAuth field makes a source OAuth-only (e.g. Hubspot). An OAuth option
    nested inside a select (e.g. Stripe's auth_method) coexists with credential options, so
    those sources route to the credentials connect page — its form still offers the OAuth
    choice alongside API keys.
    """
    for field in config.get("fields") or []:
        if isinstance(field, dict) and field.get("type") == "oauth" and field.get("kind"):
            return field
    return None


class DatabaseSchemaRequestSerializer(serializers.Serializer):
    """Validate credentials and preview available tables from a remote database.

    The request body contains source_type plus flat source-specific credential fields
    (e.g. host, port, database, user, password, schema for Postgres). The credential
    fields vary per source_type and are validated dynamically by the source registry.

    For source_type "Custom" (a user-defined REST API) the body carries `manifest_json`
    (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the
    credential for the manifest's declared auth type — `auth_token` (bearer), `auth_api_key`
    (api_key), or `auth_password` (http_basic); keep secrets in these auth_* keys, never
    inline in manifest_json. The returned tables mirror the manifest's resources, with
    detected primary keys and incremental cursors.
    """

    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to validate against.",
    )


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class ResolvedStoredCredential:
    payload: dict = dataclasses.field(repr=False)
    credential: PendingSourceCredential | None
    error_response: Response | None


class ExternalDataSourceCredentialStoreMixin:
    @extend_schema(
        request=SourceCredentialCreateSerializer,
        responses={201: SourceCredentialSerializer},
    )
    @action(methods=["POST"], detail=False)
    def store_credentials(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Validate and store credentials for a data warehouse source without creating the source.

        Backs the source connect page: the user enters credentials directly in PostHog, they are
        checked against a live connection, then stashed encrypted in a temporary store. The returned
        credential id can be passed to `setup` as {'credential_id': <id>} to create the source — so
        secrets never travel through an agent conversation. The stash is single-use: it is deleted
        as soon as `setup` consumes it, and expires after 24 hours if never consumed.
        """
        serializer = SourceCredentialCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        payload = dict(serializer.validated_data["payload"])

        for key, value in payload.items():
            if isinstance(value, str):
                payload[key] = value.strip()

        source_type_model = ExternalDataSourceType(source_type)
        source = viewset.SourceRegistry.get_source(source_type_model)

        error_response, _ = self._validate_source_config_and_credentials(source, source_type_model, payload)
        if error_response is not None:
            return error_response

        # Opportunistically purge expired stashes — there is no separate cleanup job.
        PendingSourceCredential.objects.for_team(self.team_id).filter(expires_at__lte=timezone.now()).delete()

        credential = PendingSourceCredential.objects.create(
            team_id=self.team_id,
            source_type=source_type,
            payload=payload,
            created_by=cast(User, request.user),
        )

        return Response(
            status=status.HTTP_201_CREATED,
            data=SourceCredentialSerializer(
                {
                    "credential_id": credential.id,
                    "source_type": source_type,
                    "created_at": credential.created_at,
                    "expires_at": credential.expires_at,
                }
            ).data,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return stored credentials for this source type (e.g. 'Stripe', 'Postgres').",
            )
        ],
        responses=SourceCredentialSerializer(many=True),
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def stored_credentials(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List credentials the requesting user stored via the source connect page that haven't been consumed yet.

        Returns metadata only (id, source type, timestamps) — never the secrets themselves. Stored
        credentials are scoped to their creator: only the user who filled the connect page can list
        or consume them. They are temporary too: they disappear once consumed by `setup` or when
        they expire. Newest first, so after a user confirms they've finished the connect page, the
        first entry for the source type is the one to pass to `setup`.
        """
        queryset = (
            PendingSourceCredential.objects.for_team(self.team_id)
            .filter(created_by=cast(User, request.user), expires_at__gt=timezone.now())
            .order_by("-created_at")
        )
        source_type = request.query_params.get("source_type")
        if source_type:
            queryset = queryset.filter(source_type=source_type)

        data = [
            {
                "credential_id": credential.id,
                "source_type": credential.source_type,
                "created_at": credential.created_at,
                "expires_at": credential.expires_at,
            }
            for credential in queryset
        ]
        return Response(status=status.HTTP_200_OK, data=SourceCredentialSerializer(data, many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="The source type to generate a connect link for (e.g. 'Stripe', 'Postgres', 'Hubspot').",
            )
        ],
        responses=SourceConnectLinkSerializer,
    )
    @action(methods=["GET"], detail=False)
    def connect_link(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return a secure browser link for connecting a data warehouse source.

        The link opens a minimal connect page rendering the source's full connection form — OAuth options
        included — with no table selection and no source creation. The user authenticates in their browser,
        secrets never pass through the agent, and the agent finishes setup afterwards by passing the stored
        credential id to data-warehouse-source-setup.
        """
        source_type = request.query_params.get("source_type")
        if not source_type:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Missing required parameter: source_type"},
            )
        try:
            source_type_model = ExternalDataSourceType(source_type)
        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Unknown source_type '{source_type}'"},
            )

        source = viewset.SourceRegistry.get_source(source_type_model)
        oauth_field = _find_top_level_oauth_field(source.get_source_config.model_dump())
        action_phrase = (
            f"connect their {source_type} account" if oauth_field else f"enter their {source_type} connection details"
        )

        data = {
            "source_type": source_type,
            "auth_method": "oauth" if oauth_field else "credentials",
            "connect_url": (
                f"{settings.SITE_URL}/project/{self.team_id}/data-warehouse/connect?kind={quote(str(source_type))}"
            ),
            "instructions": (
                f"Share this link with the user. They {action_phrase} directly in PostHog — never ask them to "
                "paste credentials or tokens into the chat. The page only stores the connection details; it does "
                "not create the source. Once the user confirms they're done, find the stored credential id via "
                f"data-warehouse-stored-credentials-list (source_type='{source_type}', newest first) and call "
                'data-warehouse-source-setup with {"credential_id": <id>} in the payload. Stored credentials are '
                "single-use, expire after 24 hours, and are only visible to and consumable by the PostHog user "
                "who entered them — so the page must be filled by the same user this session authenticates as."
            ),
        }
        return Response(status=status.HTTP_200_OK, data=SourceConnectLinkSerializer(data).data)
