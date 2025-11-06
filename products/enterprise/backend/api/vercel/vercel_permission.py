from rest_framework import exceptions
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from products.enterprise.backend.api.vercel.utils import expect_vercel_user_claim, get_vercel_claims


class VercelPermission(BasePermission):
    """
    Validates Vercel auth type, installation ID match, and user role.
    Vercel auth type is determined by the X-Vercel-Auth header, and can differ per endpoint.
    User roles: ADMIN can perform all operations, USER is read-only.
    See Marketplace API spec for more details.
    """

    # Actions that require ADMIN role (write operations)
    ADMIN_ONLY_ACTIONS = {"update", "partial_update", "create", "destroy"}
    # Actions that allow USER role (read-only operations)
    READ_ONLY_ACTIONS = {"list", "retrieve", "plans"}

    def has_permission(self, request: Request, view) -> bool:
        self._validate_auth_type_allowed(request, view)
        # Only validate role if this is a user auth request
        # System auth bypasses role checks
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()
        if auth_type == "user":
            self._validate_user_role(request, view)
        return True

    def has_object_permission(self, request: Request, view, obj) -> bool:
        self._validate_installation_id_match(request, view)
        return True

    def _get_supported_auth_types(self, view) -> list[str]:
        """
        Get supported auth types for the current action from the viewset.
        Each view can define an attribute like so:
        vercel_supported_auth_types = {
            "list": ["user"],
            ...
            "action_name": ["system"],
        }
        """
        return getattr(view, "vercel_supported_auth_types", {}).get(view.action, ["user", "system"])

    def _validate_auth_type_allowed(self, request: Request, view) -> None:
        """
        Validate that the auth type from X-Vercel-Auth header is allowed for this endpoint.
        Supported auth type is specified by the marketplace API spec.
        """
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()
        if not auth_type:
            raise exceptions.AuthenticationFailed("Missing X-Vercel-Auth header")

        supported_types = self._get_supported_auth_types(view)

        if auth_type not in supported_types:
            raise exceptions.PermissionDenied(
                f"Auth type '{auth_type}' not allowed for this endpoint. Supported types: {', '.join(supported_types)}"
            )

    def _validate_user_role(self, request: Request, view) -> bool:
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()

        if auth_type == "system":
            return True

        if auth_type == "user":
            user_claims = expect_vercel_user_claim(request)
            user_role = user_claims.user_role

            if view.action in self.ADMIN_ONLY_ACTIONS:
                if user_role != "ADMIN":
                    raise exceptions.PermissionDenied(
                        f"Action '{view.action}' requires ADMIN role. Current role: {user_role}"
                    )

            elif view.action in self.READ_ONLY_ACTIONS:
                if user_role not in ["ADMIN", "USER"]:
                    raise exceptions.PermissionDenied(
                        f"Action '{view.action}' requires ADMIN or USER role. Current role: {user_role}"
                    )

        return True

    def _validate_installation_id_match(self, request: Request, view) -> None:
        claims = get_vercel_claims(request)

        # installation_id when going through the vercel_installation ViewSet,
        # or parent_lookup_installation_id when going through the vercel_resource
        installation_id = view.kwargs.get("installation_id") or view.kwargs.get("parent_lookup_installation_id")

        if not installation_id:
            raise exceptions.PermissionDenied("Missing installation_id")

        if claims.installation_id != installation_id:
            raise exceptions.PermissionDenied("Installation ID mismatch")
