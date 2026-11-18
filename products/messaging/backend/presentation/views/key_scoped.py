"""The transactional email viewsets at /api/messaging/, with the project taken from the project secret API key."""

from products.messaging.backend.presentation.views.attachment_uploads import MessagingAttachmentsViewSet
from products.messaging.backend.presentation.views.message_templates import MessagingSendViewSet
from products.messaging.backend.presentation.views.topic_preferences import TopicPreferencesViewSet
from products.messaging.backend.presentation.views.transactional_email_status import MessagingEmailsViewSet


class KeyScopedMessagingSendViewSet(MessagingSendViewSet):
    team_from_project_secret_api_key = True


class KeyScopedMessagingAttachmentsViewSet(MessagingAttachmentsViewSet):
    team_from_project_secret_api_key = True


class KeyScopedMessagingEmailsViewSet(MessagingEmailsViewSet):
    team_from_project_secret_api_key = True


class KeyScopedTopicPreferencesViewSet(TopicPreferencesViewSet):
    team_from_project_secret_api_key = True
