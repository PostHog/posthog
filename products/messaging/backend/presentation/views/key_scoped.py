"""The transactional email viewsets at /api/messaging/, with the project taken from the project secret API key."""

from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.permissions import is_authenticated_via_project_secret_api_key

from products.messaging.backend.presentation.views.attachment_uploads import MessagingAttachmentsViewSet
from products.messaging.backend.presentation.views.message_templates import MessagingSendViewSet
from products.messaging.backend.presentation.views.topic_preferences import TopicPreferencesViewSet
from products.messaging.backend.presentation.views.transactional_email_status import MessagingEmailsViewSet


# These paths carry no project id, so each view sets `param_derived_from_user_current_team`, which makes the routing
# mixin read the team from `request.user.team`. Despite the name, that is not a mutable current project here: a project
# secret API key authenticates as a synthetic user whose team is fixed to the key's own project. A credential with a
# real user would resolve to the project that user last opened, the same problem as `@current`, so these views refuse
# every credential except a project secret API key.
class ProjectSecretAPIKeyOnly(BasePermission):
    message = "This endpoint accepts project secret API keys only."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return is_authenticated_via_project_secret_api_key(request)


class KeyScopedMessagingSendViewSet(MessagingSendViewSet):
    param_derived_from_user_current_team = "team_id"
    permission_classes = [IsAuthenticated, ProjectSecretAPIKeyOnly]


class KeyScopedMessagingAttachmentsViewSet(MessagingAttachmentsViewSet):
    param_derived_from_user_current_team = "team_id"
    permission_classes = [IsAuthenticated, ProjectSecretAPIKeyOnly]


class KeyScopedMessagingEmailsViewSet(MessagingEmailsViewSet):
    param_derived_from_user_current_team = "team_id"
    permission_classes = [IsAuthenticated, ProjectSecretAPIKeyOnly]


class KeyScopedTopicPreferencesViewSet(TopicPreferencesViewSet):
    param_derived_from_user_current_team = "team_id"
    permission_classes = [IsAuthenticated, ProjectSecretAPIKeyOnly]
