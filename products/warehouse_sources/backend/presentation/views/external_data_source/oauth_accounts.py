"""Serializers and endpoints for OAuth account selection."""

from __future__ import annotations

from typing import Any, cast

from django.core.cache import cache

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action
from posthog.models.integration import Integration
from posthog.permissions import TeamMemberAdminManagementPermission

from products.warehouse_sources.backend.facade.source_management import (
    IntegrationAccountListingError,
    OAuthMixin,
    filter_integration_accounts,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

from . import base, helpers


class IntegrationAccountSerializer(serializers.Serializer):
    """A selectable account/resource exposed by an OAuth integration, in the shared shape every ad
    platform produces (see ``IntegrationAccount`` in the data-imports common module). One serializer
    and one frontend selector work across all platforms."""

    value = serializers.CharField(
        help_text="The identifier stored in the source config and used for API calls (numeric account id as a string, a site url, etc.)."
    )
    display_name = serializers.CharField(help_text="Primary human-readable label for the account.")
    is_primary = serializers.BooleanField(
        help_text="True when this account belongs to the connected user's own (primary) account context, rather than one they merely have access to. Sorted/marked first."
    )
    badges = serializers.ListField(
        child=serializers.CharField(),
        help_text="Short status chips for the account, e.g. ['Active'] or ['Pause'].",
    )
    group = serializers.CharField(
        allow_null=True,
        help_text="Optional grouping label for hierarchical platforms (e.g. the owning customer/manager name).",
    )
    secondary_text = serializers.CharField(
        allow_null=True,
        help_text="Extra identifier shown in parentheses and searchable, e.g. the alphanumeric account number.",
    )


class IntegrationAccountsResponseSerializer(serializers.Serializer):
    accounts = IntegrationAccountSerializer(
        many=True,
        help_text="All accounts the connected integration can access.",
    )


class AccountPickerManagementPermission(TeamMemberAdminManagementPermission):
    """Admin gate for the account picker, with a message the customer can act on.

    The base message names no next step. Free entry stays open on the account field, so a
    member who cannot list accounts can still finish the source by filling the account in.
    """

    message = (
        "You need admin access to this project to list the accounts this connection can reach. "
        "Ask an admin to finish the setup, or fill in the account yourself."
    )


class ExternalDataSourceOAuthAccountsMixin(base.ExternalDataSourceViewSetBase):
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                required=True,
                description="The data warehouse source type (e.g. 'BingAds', 'GoogleSearchConsole').",
            ),
            OpenApiParameter(
                name="integration_id",
                type=int,
                required=True,
                description="The OAuth integration id whose accounts should be listed.",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                required=False,
                description="Optional case-insensitive filter over account name/value, for sources whose "
                "resource list is large (e.g. GitHub repositories).",
            ),
        ],
        responses={200: IntegrationAccountsResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="oauth_accounts")
    def oauth_accounts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List the accounts/properties a connected OAuth integration exposes, in the shared
        IntegrationAccount shape. The logic lives in each source (via OAuthMixin.get_oauth_accounts);
        this endpoint just routes by source type, applies the optional search filter, and serializes."""
        source_type = request.query_params.get("source_type")
        integration_id = request.query_params.get("integration_id")
        search = request.query_params.get("search") or None
        if not source_type or not integration_id:
            raise ValidationError("source_type and integration_id are required")

        try:
            integration_id_int = int(integration_id)
        except ValueError:
            raise ValidationError("integration_id must be an integer")

        try:
            source = base.SourceRegistry.get_source(cast(ExternalDataSourceType, source_type))
        except ValueError:
            raise ValidationError(f"Unknown source type: {source_type}")

        if not isinstance(source, OAuthMixin):
            raise ValidationError(f"Source type {source_type} does not support listing OAuth accounts")

        # The integration id is caller-supplied and each source looks it up by (id, team_id) only, so
        # without this a same-team integration of a different provider would be accepted here and its
        # OAuth token handed to this source's provider. Pin it to the kind(s) the source's picker
        # declares before any of that runs.
        expected_kinds = helpers.get_oauth_integration_kinds(source.get_source_config.fields)
        if not expected_kinds:
            raise ValidationError(f"Source type {source_type} does not support listing OAuth accounts")
        if not Integration.objects.filter(
            id=integration_id_int, team_id=self.team_id, kind__in=expected_kinds
        ).exists():
            # One message for "gone" and "wrong kind" alike: from the UI both mean the picker is holding
            # a connection this source can't use, and neither tells the caller anything about ids it
            # isn't already allowed to see.
            raise ValidationError(
                f"No {source_type} connection was found for this integration. Please reconnect the integration."
            )

        cache_key = f"oauth_accounts/{self.team_id}/{source_type}/{integration_id_int}/{search or ''}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            accounts = source.get_oauth_accounts(integration_id_int, self.team_id, search=search)
        except NotImplementedError:
            # An OAuth source that hasn't implemented account listing yet (passes the isinstance check).
            raise ValidationError(f"Source type {source_type} does not support listing OAuth accounts")
        except IntegrationAccountListingError as e:
            # Actionable, customer-side failure (revoked/expired token, deleted integration, the provider
            # rejecting the credentials) — surface the message as a 400. Anything else (e.g. a bare
            # ValueError from an internal bug) stays uncaught and becomes a 500 so monitors see it.
            raise ValidationError(str(e))

        # Belt-and-suspenders: sources that support server-side search already return matching results;
        # this filters sources that returned a full list and ignored `search`.
        accounts = filter_integration_accounts(accounts, search)
        response_data = {"accounts": IntegrationAccountSerializer(accounts, many=True).data}
        # Don't cache an empty result: a transient provider hiccup that returns [] without raising would
        # otherwise poison the picker for 60s for every admin on the team.
        if accounts:
            cache.set(cache_key, response_data, 60)
        return Response(response_data)
