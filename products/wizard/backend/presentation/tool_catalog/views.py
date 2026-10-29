from django.http import HttpResponse
from django.utils.cache import patch_cache_control

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.presentation.tool_catalog.serializers import WizardToolCatalogSerializer

# The catalog only changes on deploy, so clients and proxies can reuse a response for an hour.
CACHE_MAX_AGE_SECONDS = 60 * 60


class WizardToolCatalogViewSet(viewsets.ViewSet):
    # Public: the wizard scans a codebase before the user logs in, and the catalog is in the public repo.
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    scope_object = None
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        responses={200: WizardToolCatalogSerializer},
        summary="Get the wizard tool catalog",
        description="Every tool the wizard can detect in a codebase, with the signals that identify it.",
    )
    def list(self, request: Request) -> HttpResponse:
        response = HttpResponse(wizard_facade.get_tool_catalog_json(), content_type="application/json")
        patch_cache_control(response, public=True, max_age=CACHE_MAX_AGE_SECONDS)
        return response
