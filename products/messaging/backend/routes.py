from django.urls import URLPattern, re_path

from posthog.api.routing import RouterRegistry

from products.messaging.backend.presentation.views.message_categories import MessageCategoryViewSet
from products.messaging.backend.presentation.views.message_preferences import MessagePreferencesViewSet
from products.messaging.backend.presentation.views.message_suppression import MessageSuppressionViewSet
from products.messaging.backend.presentation.views.message_templates import (
    MessageTemplatesViewSet,
    MessagingSendViewSet,
)
from products.messaging.backend.presentation.views.provider_imports import ProviderImportViewSet
from products.messaging.backend.presentation.views.supabase_auth_emails import (
    SupabaseAuthEmailsViewSet,
    SupabaseSendEmailHookView,
)
from products.messaging.backend.presentation.views.transactional_email_status import MessagingEmailsViewSet

webhook_urlpatterns: list[URLPattern] = [
    re_path(
        r"^supabase/(?P<team_id>\d+)/send-email/?$",
        SupabaseSendEmailHookView.as_view(),
        name="messaging_supabase_send_email_hook",
    ),
]


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"messaging_templates", MessageTemplatesViewSet, "project_messaging_templates", ["team_id"]
    )
    routers.projects.register(
        r"messaging_categories", MessageCategoryViewSet, "project_messaging_categories", ["team_id"]
    )
    routers.projects.register(
        r"messaging_preferences", MessagePreferencesViewSet, "project_messaging_preferences", ["team_id"]
    )
    # New endpoint — register under /api/projects/ only, not the dual-route legacy shim.
    routers.projects.register(
        r"messaging_suppressions", MessageSuppressionViewSet, "project_messaging_suppressions", ["team_id"]
    )
    routers.projects.register(r"messaging/send", MessagingSendViewSet, "project_messaging_send", ["team_id"])
    routers.projects.register(
        r"messaging_provider_imports", ProviderImportViewSet, "project_messaging_provider_imports", ["team_id"]
    )
    routers.projects.register(
        r"messaging_supabase_auth_emails",
        SupabaseAuthEmailsViewSet,
        "project_messaging_supabase_auth_emails",
        ["team_id"],
    )
    routers.projects.register(r"messaging/emails", MessagingEmailsViewSet, "project_messaging_emails", ["team_id"])
