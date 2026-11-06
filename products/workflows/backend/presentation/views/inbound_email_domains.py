from typing import Any
from uuid import UUID

from django.db import IntegrityError

import posthoganalytics
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.workflows.backend.facade.contracts import InboundDomain, InboundDomainCheck
from products.workflows.backend.facade.enums import (
    InboundDomainCheckState,
    InboundEmailDomainKind,
    InboundEmailDomainStatus,
)
from products.workflows.backend.facade.received_emails import (
    InboundDomainError,
    check_inbound_domain,
    create_inbound_domain,
    delete_inbound_domain,
    get_inbound_domain_overview,
    preflight_inbound_domain,
    use_receiving_address,
)

INBOUND_EMAIL_FLAG = "workflows-inbound-email"


def require_inbound_email(team: Any) -> None:
    enabled = posthoganalytics.feature_enabled(
        INBOUND_EMAIL_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )
    if not enabled:
        raise NotFound()


class InboundDomainSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The domain's ID.")
    domain = serializers.CharField(help_text="Mail to any address at this domain reaches this project.")
    kind = serializers.ChoiceField(
        choices=InboundEmailDomainKind.choices,
        help_text="`generated` is a ready-made address on a PostHog domain. `custom` is the project's own domain.",
    )
    status = serializers.ChoiceField(
        choices=InboundEmailDomainStatus.choices,
        help_text="`pending` waits for its MX record. Mail is only accepted once `active`.",
    )
    mx_checked_at = serializers.DateTimeField(allow_null=True, help_text="When the MX record was last looked up.")
    activated_at = serializers.DateTimeField(allow_null=True, help_text="When the domain started receiving.")
    daily_limit_reached_at = serializers.DateTimeField(
        allow_null=True, help_text="When mail to the project last went over the daily limit and was dropped."
    )
    created_at = serializers.DateTimeField(help_text="When the domain was added.")


class InboundDomainsOverviewSerializer(serializers.Serializer):
    results = InboundDomainSerializer(many=True, help_text="The project's receiving domains.")
    generated_addresses_available = serializers.BooleanField(
        help_text="Whether this instance offers ready-made addresses."
    )
    verified_sending_domains = serializers.ListField(
        child=serializers.CharField(), help_text="Domains the project proved it owns, which can receive mail."
    )
    mx_host = serializers.CharField(help_text="The host an MX record has to point at.")
    mx_priority = serializers.IntegerField(help_text="The priority to give the MX record.")
    default_subdomain = serializers.CharField(help_text="The subdomain suggested for receiving.")
    retention_days = serializers.IntegerField(help_text="How many days received email is kept.")


class InboundDomainCheckSerializer(serializers.Serializer):
    domain = InboundDomainSerializer(help_text="The domain after the check.")
    state = serializers.ChoiceField(
        choices=InboundDomainCheckState.choices,
        help_text="The result of looking up the MX record.",
    )
    found = serializers.ListField(child=serializers.CharField(), help_text="The MX records found, as `priority host`.")


class InboundDomainPreflightRequestSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=253, help_text="The domain to check, such as `inbound.example.com`.")


class InboundDomainPreflightSerializer(serializers.Serializer):
    domain = serializers.CharField(help_text="The domain as it would be stored.")
    eligible = serializers.BooleanField(help_text="Whether the project can receive on this domain.")
    reason = serializers.CharField(help_text="Why not, in words to show a person. Empty when eligible.")
    verified_parent = serializers.CharField(help_text="The verified sending domain that proves ownership.")
    whole_domain = serializers.BooleanField(help_text="True when this is the verified domain itself, not a subdomain.")
    existing_mx = serializers.ListField(
        child=serializers.CharField(),
        help_text="Mail hosts the domain already points at. Mail would move away from them.",
    )
    points_here = serializers.BooleanField(help_text="True when an MX record already points at PostHog.")
    dns_answered = serializers.BooleanField(help_text="False when DNS did not answer, so `existing_mx` is unknown.")


class InboundDomainCreateSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=253, help_text="The domain to receive on, such as `inbound.example.com`.")
    confirm_move_mail = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Required when the domain has mail hosts or is a whole domain, because receiving moves all its mail "
        "to PostHog.",
    )


class ReceivingAddressRequestSerializer(serializers.Serializer):
    rotate = serializers.BooleanField(
        required=False, default=False, help_text="Replace the address. Mail to the old one stops being accepted."
    )


def _domain_data(domain: InboundDomain) -> dict[str, Any]:
    return {
        "id": domain.id,
        "domain": domain.domain,
        "kind": domain.kind.value,
        "status": domain.status.value,
        "mx_checked_at": domain.mx_checked_at,
        "activated_at": domain.activated_at,
        "daily_limit_reached_at": domain.daily_limit_reached_at,
        "created_at": domain.created_at,
    }


def _check_data(check: InboundDomainCheck) -> dict[str, Any]:
    return {"domain": _domain_data(check.domain), "state": check.state, "found": list(check.found)}


class _PageSchema(AutoSchema):
    # The list returns one overview object, so drf-spectacular must not wrap it in an array.
    def _is_list_view(self, serializer: object = None) -> bool:
        return False


_DOMAIN_ID_PARAMETER = OpenApiParameter(
    name="id", type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, description="The domain's ID."
)


class InboundEmailDomainViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    schema = _PageSchema()
    scope_object = "hog_flow"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["create", "destroy", "preflight", "verify", "receiving_address"]
    # Every action works on the whole project's receiving, so access to one workflow isn't enough.
    requires_resource_level_access = True

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        require_inbound_email(self.team)

    def _created_by_id(self) -> int | None:
        return self.request.user.id if isinstance(self.request.user, User) else None

    @validated_request(
        responses={200: OpenApiResponse(response=InboundDomainsOverviewSerializer)},
        summary="List receiving domains",
        operation_id="inbound_email_domains_list",
        description="List the project's receiving domains, and what it needs to add another.",
    )
    def list(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        overview = get_inbound_domain_overview(self.team_id)
        return Response(
            InboundDomainsOverviewSerializer(
                {
                    "results": [_domain_data(domain) for domain in overview.domains],
                    "generated_addresses_available": overview.generated_addresses_available,
                    "verified_sending_domains": list(overview.verified_sending_domains),
                    "mx_host": overview.mx_host,
                    "mx_priority": overview.mx_priority,
                    "default_subdomain": overview.default_subdomain,
                    "retention_days": overview.retention_days,
                }
            ).data
        )

    @validated_request(
        request_serializer=InboundDomainCreateSerializer,
        responses={
            201: OpenApiResponse(response=InboundDomainCheckSerializer),
            400: OpenApiResponse(description="The domain isn't eligible, or moving its mail wasn't confirmed."),
        },
        summary="Add a receiving domain",
        operation_id="inbound_email_domains_create",
        description="Add a verified sending domain, or a subdomain of one, and look up its MX record.",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        try:
            check = create_inbound_domain(
                self.team_id,
                request.validated_data["domain"],
                confirm_move_mail=request.validated_data["confirm_move_mail"],
                created_by_id=self._created_by_id(),
            )
        except InboundDomainError as error:
            raise ValidationError({"domain": error.detail}, code=error.code)
        except IntegrityError:
            raise ValidationError({"domain": "This domain was just added. Reload the page."}, code="conflict")
        return Response(InboundDomainCheckSerializer(_check_data(check)).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=InboundDomainPreflightRequestSerializer,
        responses={200: OpenApiResponse(response=InboundDomainPreflightSerializer)},
        summary="Check a domain before adding it",
        operation_id="inbound_email_domains_preflight",
        description="Say whether the project can receive on a domain, and which mail hosts would stop getting its mail.",
    )
    @action(detail=False, methods=["post"])
    def preflight(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        result = preflight_inbound_domain(self.team_id, request.validated_data["domain"])
        return Response(
            InboundDomainPreflightSerializer(
                {
                    "domain": result.domain,
                    "eligible": result.eligible,
                    "reason": result.reason,
                    "verified_parent": result.verified_parent,
                    "whole_domain": result.whole_domain,
                    "existing_mx": list(result.existing_mx),
                    "points_here": result.points_here,
                    "dns_answered": result.dns_answered,
                }
            ).data
        )

    @extend_schema(
        parameters=[_DOMAIN_ID_PARAMETER],
        request=None,
        responses={200: InboundDomainCheckSerializer, 404: OpenApiResponse(description="No such domain.")},
        summary="Check a domain's MX record",
        description="Look up the MX record now. The domain starts receiving as soon as the record is right.",
    )
    @action(detail=True, methods=["post"])
    def verify(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        check = check_inbound_domain(self.team_id, _domain_id(pk))
        if check is None:
            raise NotFound()
        return Response(InboundDomainCheckSerializer(_check_data(check)).data)

    @validated_request(
        request_serializer=ReceivingAddressRequestSerializer,
        responses={
            200: OpenApiResponse(response=InboundDomainSerializer),
            400: OpenApiResponse(description="This instance doesn't offer ready-made addresses."),
        },
        summary="Get or replace the ready-made address",
        operation_id="inbound_email_domains_receiving_address",
        description="Get the project's ready-made receiving domain, creating it the first time. Needs no DNS.",
    )
    @action(detail=False, methods=["post"], url_path="receiving_address")
    def receiving_address(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        try:
            domain = use_receiving_address(
                self.team_id, rotate=request.validated_data["rotate"], created_by_id=self._created_by_id()
            )
        except InboundDomainError as error:
            raise ValidationError({"detail": error.detail}, code=error.code)
        return Response(InboundDomainSerializer(_domain_data(domain)).data)

    @extend_schema(
        parameters=[_DOMAIN_ID_PARAMETER],
        responses={204: None, 404: OpenApiResponse(description="No such custom domain.")},
        summary="Remove a receiving domain",
        description="Stop accepting mail for a custom domain. Mail already received stays until it expires.",
    )
    def destroy(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        if not delete_inbound_domain(self.team_id, _domain_id(pk)):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _domain_id(value: str | None) -> UUID:
    try:
        return UUID(str(value))
    except ValueError:
        raise NotFound()
