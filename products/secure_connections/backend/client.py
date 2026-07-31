from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

import requests


class SecureConnectionServiceError(Exception):
    pass


class SecureConnectionServiceNotConfigured(SecureConnectionServiceError):
    pass


@dataclass(frozen=True)
class ServiceTenant:
    id: str
    slug: str


class SecureConnectionServiceClient:
    def __init__(self, timeout_seconds: int = 10) -> None:
        self._management_url = settings.SECURE_CONNECTION_MANAGEMENT_URL.rstrip("/")
        self._control_url = settings.SECURE_CONNECTION_CONTROL_URL.rstrip("/")
        self._admin_token = settings.SECURE_CONNECTION_ADMIN_TOKEN
        self._public_control_url = settings.SECURE_CONNECTION_PUBLIC_CONTROL_URL.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def public_control_url(self) -> str:
        return self._public_control_url

    def _require_configuration(self) -> None:
        if not self._management_url or not self._control_url or not self._admin_token or not self._public_control_url:
            raise SecureConnectionServiceNotConfigured("The secure connection service is not configured.")

    def _management_headers(self) -> dict[str, str]:
        self._require_configuration()
        return {"Authorization": f"Bearer {self._admin_token}", "Content-Type": "application/json"}

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object] | None = None,
    ) -> requests.Response:
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as error:
            raise SecureConnectionServiceError("Could not reach the secure connection service.") from error
        return response

    def get_tenant(self, slug: str) -> ServiceTenant | None:
        response = self._request(
            "GET",
            f"{self._management_url}/admin/tenants/{slug}",
            headers=self._management_headers(),
        )
        if response.status_code == 404:
            return None
        self._raise_for_status(response)
        body = response.json()
        return ServiceTenant(id=body["id"], slug=body["slug"])

    def create_tenant(self, *, team_id: int, slug: str) -> ServiceTenant:
        response = self._request(
            "POST",
            f"{self._management_url}/admin/tenants",
            headers=self._management_headers(),
            json={"external_id": str(team_id), "slug": slug},
        )
        if response.status_code == 409:
            tenant = self.get_tenant(slug)
            if tenant is not None:
                return tenant
        self._raise_for_status(response)
        body = response.json()
        return ServiceTenant(id=body["id"], slug=body["slug"])

    def mint_enrollment_key(self, tenant_id: str) -> str:
        response = self._request(
            "POST",
            f"{self._management_url}/admin/tenants/{tenant_id}/keys",
            headers=self._management_headers(),
            json={"reusable": True, "ttl_seconds": 86400},
        )
        self._raise_for_status(response)
        return response.json()["key"]

    def mint_advertisement_token(self, tenant_id: str) -> str:
        response = self._request(
            "POST",
            f"{self._management_url}/admin/tenants/{tenant_id}/tokens",
            headers=self._management_headers(),
            json={
                "name": "connection-proxy",
                "audience": "burrow-control",
                "scopes": ["advertise"],
                "ttl_seconds": 31536000,
            },
        )
        self._raise_for_status(response)
        return response.json()["token"]

    def list_connections(self, tenant_id: str) -> list[dict[str, object]]:
        token_response = self._request(
            "POST",
            f"{self._management_url}/admin/tenants/{tenant_id}/tokens",
            headers=self._management_headers(),
            json={
                "name": "posthog-status-check",
                "audience": "burrow-control",
                "scopes": ["discover"],
                "ttl_seconds": 60,
            },
        )
        self._raise_for_status(token_response)
        token = token_response.json()["token"]
        response = self._request(
            "GET",
            f"{self._control_url}/api/tenants/{tenant_id}/connections",
            headers={"Authorization": f"Bearer {token}"},
        )
        self._raise_for_status(response)
        return response.json()["connections"]

    def _raise_for_status(self, response: requests.Response) -> None:
        if response.status_code >= 400:
            raise SecureConnectionServiceError(f"The secure connection service returned status {response.status_code}.")
