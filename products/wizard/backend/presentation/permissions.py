from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.auth import IDJagAccessTokenAuthentication, OAuthAccessTokenAuthentication, SessionAuthentication


class WizardRunSessionAuthenticationRequired(BasePermission):
    message = "Sign in to use Wizard runs."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "action", None) in ("create", "partial_update"):
            if isinstance(request.successful_authenticator, OAuthAccessTokenAuthentication):
                return True
        return isinstance(request.successful_authenticator, SessionAuthentication)


class WizardInstallAuthenticationRequired(BasePermission):
    """
    Setup runs start from the browser or from an agent that holds an OAuth or ID-JAG access token.
    Personal API keys stay out, so every agent caller was authorized for that client, either on a
    consent screen or by an organization admin who trusted the identity provider.
    """

    message = "Sign in, or connect through OAuth, to start a setup run."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(
            request.successful_authenticator,
            SessionAuthentication | OAuthAccessTokenAuthentication | IDJagAccessTokenAuthentication,
        )
