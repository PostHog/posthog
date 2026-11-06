from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.auth import OAuthAccessTokenAuthentication, SessionAuthentication


class WizardRunSessionAuthenticationRequired(BasePermission):
    message = "Sign in to use Wizard runs."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "action", None) in ("create", "partial_update"):
            if isinstance(request.successful_authenticator, OAuthAccessTokenAuthentication):
                return True
        return isinstance(request.successful_authenticator, SessionAuthentication)


class WizardInstallAuthenticationRequired(BasePermission):
    """
    Setup runs start from the browser or from an agent that holds an OAuth access token.
    Personal API keys stay out, so every agent caller went through a consent screen.
    """

    message = "Sign in, or connect through OAuth, to start a setup run."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.successful_authenticator, SessionAuthentication | OAuthAccessTokenAuthentication)
