from typing import Any

from rest_framework import decorators, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from products.enterprise.backend.api.authentication import VercelAuthentication
from products.enterprise.backend.api.vercel.vercel_error_mixin import VercelErrorResponseMixin
from products.enterprise.backend.api.vercel.vercel_permission import VercelPermission
from products.enterprise.backend.api.vercel.vercel_region_proxy_mixin import VercelRegionProxyMixin
from products.enterprise.backend.vercel.integration import VercelIntegration


class VercelProductViewSet(VercelRegionProxyMixin, VercelErrorResponseMixin, viewsets.GenericViewSet):
    authentication_classes = [VercelAuthentication]
    permission_classes = [VercelPermission]
    lookup_field = "product_slug"

    vercel_supported_auth_types = {
        "plans": ["user", "system"],
    }

    @decorators.action(detail=True, methods=["get"])
    def plans(self, _request: Request, *_args: Any, **_kwargs: Any) -> Response:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#list-billing-plans-for-product
        """
        product_slug = self.kwargs.get("product_slug", "")
        return Response(VercelIntegration.get_product_plans(product_slug))
