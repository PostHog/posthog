import re
import json
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

import requests
import structlog
from rest_framework import exceptions
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.organization_integration import OrganizationIntegration

from products.enterprise.backend.api.authentication import VercelAuthentication

logger = structlog.get_logger(__name__)


class VercelRegionProxyMixin:
    """
    Mixin for handling Vercel region-based request routing.

    The Vercel integration configuration only supports one endpoint to communicate with.
    Therefore we need to proxy requests to the appropriate region.
    We do this by first checking if a Vercel installation exists in the US.
    If it doesn't exist we forward to the EU region.
    """

    CACHE_TTL = 300
    PROXY_TIMEOUT = 10
    US_DOMAIN = getattr(settings, "REGION_US_DOMAIN", "us.posthog.com")
    EU_DOMAIN = getattr(settings, "REGION_EU_DOMAIN", "eu.posthog.com")

    @property
    def is_dev_env(self) -> bool:
        return settings.SITE_URL.startswith("http://localhost") or settings.DEBUG

    @property
    def current_region(self) -> Optional[str]:
        if settings.SITE_URL == f"https://{self.US_DOMAIN}":
            return "us"
        elif settings.SITE_URL == f"https://{self.EU_DOMAIN}":
            return "eu"
        return None

    def _get_cached_installation_status(self, installation_id: str) -> bool:
        cache_key = f"vercel_installation_exists:{installation_id}"

        result = cache.get(cache_key)
        if result is None:
            result = OrganizationIntegration.objects.filter(
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL, integration_id=installation_id
            ).exists()
            self.set_installation_cache(installation_id, result)

        return result

    def invalidate_installation_cache(self, installation_id: str) -> None:
        """Invalidate cache after installation create/update/delete operations"""
        cache_key = f"vercel_installation_exists:{installation_id}"
        cache.delete(cache_key)

    def set_installation_cache(self, installation_id: str, exists: bool) -> None:
        """Update cache after installation operations"""
        cache_key = f"vercel_installation_exists:{installation_id}"
        cache.set(cache_key, exists, timeout=self.CACHE_TTL)

    def _extract_installation_id(self, request: HttpRequest) -> Optional[str]:
        try:
            if not all([request.META.get("HTTP_AUTHORIZATION"), request.META.get("HTTP_X_VERCEL_AUTH")]):
                return None

            drf_request = Request(request)
            auth_result = VercelAuthentication().authenticate(drf_request)
            return auth_result[0].claims.installation_id if auth_result else None

        except (exceptions.AuthenticationFailed, exceptions.ValidationError):
            return None

    def _extract_data_region_from_metadata(self, request: HttpRequest) -> Optional[str]:
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            metadata = body.get("metadata", {})
            data_region = metadata.get("data_region")

            if data_region in ["US", "EU"]:
                return data_region.lower()

        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass

        return None

    def _is_upsert_operation(self, request: HttpRequest) -> bool:
        if request.method != "PUT":
            return False

        pattern = r"^/api/vercel/v1/installations/[^/]+/?$"  #  /api/vercel/v1/installations/{installation_id}
        return bool(re.match(pattern, request.path))

    def _proxy_to_eu(self, request: HttpRequest) -> Response:
        if self.current_region != "us":
            raise exceptions.APIException("Can only proxy from US region")

        parsed_url = urlparse(request.build_absolute_uri())
        target_url = urlunparse(parsed_url._replace(netloc=self.EU_DOMAIN))

        try:
            response = requests.request(
                method=request.method or "GET",
                url=target_url,
                headers=dict(request.headers),  # Django's headers object works directly
                params=dict(request.GET.lists()) if request.GET else None,
                data=request.body or None,
                timeout=self.PROXY_TIMEOUT,
            )

            logger.info(
                "Proxied request to EU region",
                target_url=target_url,
                status_code=response.status_code,
                integration="vercel",
            )

            content_type = response.headers.get("content-type", "")
            if not content_type.startswith(("application/json", "text/")):
                logger.warning("Unexpected content type from proxy", content_type=content_type)

            try:
                data = response.json() if response.content else {}
            except ValueError:
                data = {"error": "Invalid response from alternate region"}

            return Response(data=data, status=response.status_code, content_type="application/json")

        except requests.exceptions.RequestException as e:
            logger.exception(
                "Failed to proxy request to EU region",
                url=target_url,
                error=str(e),
                integration="vercel",
            )
            raise exceptions.APIException("Unable to proxy request to EU region")

    def _should_proxy_to_eu(self, installation_id: str | None, request: HttpRequest) -> bool:
        if not installation_id or self.current_region != "us":
            return False

        # Handle upsert operations with data_region metadata, because we can't the installation_id to a region yet.
        # data_region metadata is set by the Vercel user when the installation is created.
        if self._is_upsert_operation(request):
            data_region = self._extract_data_region_from_metadata(request)
            if data_region:
                return data_region == "eu"

        # Normal logic: US proxies to EU if installation doesn't exist
        return not self._get_cached_installation_status(installation_id)

    def _handle_missing_installation(self, installation_id: str) -> None:
        logger.info(
            "Installation not found and no proxy target configured",
            current_region=self.current_region,
            installation_id=installation_id,
            integration="vercel",
        )
        raise exceptions.NotFound("Installation not found")

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if self.is_dev_env or not self.current_region:
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

        installation_id = self._extract_installation_id(request)

        # If we should proxy to EU, try to do so
        if self._should_proxy_to_eu(installation_id, request):
            logger.info(
                "Proxying to EU region",
                current_region=self.current_region,
                installation_id=installation_id,
                integration="vercel",
            )
            try:
                drf_response = self._proxy_to_eu(request)
                content = json.dumps(drf_response.data) if drf_response.data else "{}"
                return HttpResponse(content=content, status=drf_response.status_code, content_type="application/json")
            except exceptions.APIException as e:
                logger.warning(
                    "Proxy to EU failed, falling back to normal processing",
                    current_region=self.current_region,
                    installation_id=installation_id,
                    error=str(e),
                    integration="vercel",
                )

        # If we can't proxy, nor is the installation found, we return a 404
        elif installation_id and not self._get_cached_installation_status(installation_id):
            self._handle_missing_installation(installation_id)

        # If we can't proxy, and the installation exists, we return the response from the current region
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
