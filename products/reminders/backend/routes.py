from posthog.api.routing import RouterRegistry

from products.reminders.backend.api import reminder


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"reminders", reminder.ReminderViewSet, "project_reminders", ["project_id"])
