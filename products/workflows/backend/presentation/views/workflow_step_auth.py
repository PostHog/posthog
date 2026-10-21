import uuid
from typing import Any

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import ScopedServiceJWTAuthentication


class WorkflowStepJWTAuthentication(ScopedServiceJWTAuthentication):
    """Authenticates a workflow step's call back into Django. Subclasses set `purpose`."""

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # Read from the verified token, never the body, so one workflow's token can't act for another.
        try:
            hog_flow_id = uuid.UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, hog_flow_id
