"""The transactional email API at /api/messaging/, for project secret API keys.

These routes serve the same viewsets as /api/projects/:project_id/messaging/, without a project in the path.
"""

from typing import Literal, Optional

from rest_framework.authentication import BaseAuthentication

from posthog.api.documentation import PostHogAutoSchema
from posthog.auth import ProjectSecretAPIKeyAuthentication

from products.messaging.backend.presentation.views.attachment_uploads import MessagingAttachmentsViewSet
from products.messaging.backend.presentation.views.message_templates import MessagingSendViewSet
from products.messaging.backend.presentation.views.topic_preferences import TopicPreferencesViewSet
from products.messaging.backend.presentation.views.transactional_email_status import MessagingEmailsViewSet


class KeyScopedAutoSchema(PostHogAutoSchema):
    # Both routes of a view would otherwise derive the same operation id from the path after the project.
    def get_operation_id(self) -> str:
        return f"key_scoped_{super().get_operation_id()}"


class KeyScopedViewMixin:
    # The project comes from the authenticated user, and a project secret API key's user is pinned to the key's
    # project. Any credential that carries a real user would resolve to the project that user last opened, so these
    # routes accept project secret API keys and nothing else.
    param_derived_from_user_current_team: Optional[Literal["team_id", "project_id"]] = "team_id"
    force_include_in_api_docs = True
    schema = KeyScopedAutoSchema()

    def get_authenticators(self) -> list[BaseAuthentication]:
        return [ProjectSecretAPIKeyAuthentication()]


class KeyScopedMessagingSendViewSet(KeyScopedViewMixin, MessagingSendViewSet):
    pass


class KeyScopedMessagingAttachmentsViewSet(KeyScopedViewMixin, MessagingAttachmentsViewSet):
    pass


class KeyScopedMessagingEmailsViewSet(KeyScopedViewMixin, MessagingEmailsViewSet):
    pass


class KeyScopedTopicPreferencesViewSet(KeyScopedViewMixin, TopicPreferencesViewSet):
    pass
