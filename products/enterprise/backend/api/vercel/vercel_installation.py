import re
from typing import Any

from rest_framework import decorators, exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.organization_integration import OrganizationIntegration

from products.enterprise.backend.api.authentication import VercelAuthentication
from products.enterprise.backend.api.vercel.utils import expect_vercel_user_claim
from products.enterprise.backend.api.vercel.vercel_error_mixin import VercelErrorResponseMixin
from products.enterprise.backend.api.vercel.vercel_permission import VercelPermission
from products.enterprise.backend.api.vercel.vercel_region_proxy_mixin import VercelRegionProxyMixin
from products.enterprise.backend.vercel.integration import VercelIntegration


class VercelCredentialsSerializer(serializers.Serializer):
    access_token = serializers.CharField(help_text="Access token authorizes marketplace and integration APIs.")
    token_type = serializers.CharField(help_text="The type of token (default: Bearer).")


class VercelContactSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Contact email address for the account.")
    name = serializers.CharField(required=False, allow_blank=True, help_text="Contact name for the account (optional).")


class VercelAccountSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, help_text="Account name (optional).")
    url = serializers.URLField(help_text="URL of the account.")
    contact = VercelContactSerializer(help_text="Contact information for the account.")


class UpsertInstallationPayloadSerializer(serializers.Serializer):
    scopes = serializers.ListField(
        child=serializers.CharField(), min_length=1, help_text="Array of scopes, must have at least one. Min Length: 1"
    )
    acceptedPolicies = serializers.DictField(
        child=serializers.JSONField(),
        help_text='Policies accepted by the customer. Example: { "toc": "2024-02-28T10:00:00Z" }',
    )
    credentials = VercelCredentialsSerializer(
        help_text="The service-account access token to access marketplace and integration APIs on behalf of a customer's installation."
    )
    account = VercelAccountSerializer(
        help_text="The account information for this installation. Use Get Account Info API to re-fetch this data post installation."
    )


class UpdateInstallationPayloadSerializer(serializers.Serializer):
    billingPlanId = serializers.CharField(help_text='Partner-provided billing plan. Example: "pro200"')


INSTALLATION_ID_PATTERN = re.compile(r"^icfg_[A-Za-z0-9]{24}$")


def validate_installation_id(installation_id: str | None) -> str:
    if not installation_id:
        raise exceptions.ValidationError({"installation_id": "Missing installation_id in URL."})

    if not INSTALLATION_ID_PATTERN.match(installation_id):
        raise exceptions.ValidationError({"installation_id": "Invalid installation_id format."})

    return installation_id


class VercelInstallationViewSet(VercelRegionProxyMixin, VercelErrorResponseMixin, viewsets.GenericViewSet):
    lookup_field = "installation_id"
    authentication_classes = [VercelAuthentication]
    permission_classes = [VercelPermission]

    vercel_supported_auth_types = {
        "update": ["user"],
        "partial_update": ["user"],
        "destroy": ["user", "system"],
        "retrieve": ["system"],
        "plans": ["system"],
    }

    def get_object(self):
        installation_id = validate_installation_id(self.kwargs.get("installation_id"))

        try:
            installation = OrganizationIntegration.objects.get(
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL, integration_id=installation_id
            )
            return installation
        except OrganizationIntegration.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#upsert-installation
        """
        serializer = UpsertInstallationPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(detail=serializer.errors)

        installation_id = validate_installation_id(self.kwargs.get("installation_id"))
        user_claim = expect_vercel_user_claim(request)
        VercelIntegration.upsert_installation(installation_id, serializer.validated_data, user_claim)

        # Update cache since installation now exists
        self.set_installation_cache(installation_id, True)
        return Response(status=204)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#get-installation
        """
        installation_id = validate_installation_id(self.kwargs.get("installation_id"))
        response_data = VercelIntegration.get_installation_billing_plan(installation_id)
        return Response(response_data, status=200)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#update-installation
        """
        serializer = UpdateInstallationPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(detail=serializer.errors)

        installation_id = validate_installation_id(self.kwargs.get("installation_id"))
        VercelIntegration.update_installation(installation_id, serializer.validated_data.get("billingPlanId"))

        # Ensure cache reflects installation still exists
        self.set_installation_cache(installation_id, True)

        return Response(status=204)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#delete-installation
        """
        installation_id = validate_installation_id(self.kwargs.get("installation_id"))
        response_data = VercelIntegration.delete_installation(installation_id)

        return Response(response_data, status=200)

    @decorators.action(detail=True, methods=["get"])
    def plans(self, _request: Request, *_args: Any, **_kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#get-installation-plans
        """
        return Response({"plans": VercelIntegration.get_vercel_plans()})
