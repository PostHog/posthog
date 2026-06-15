from posthog.api.routing import RouterRegistry

from products.reminders.backend.api import reminder


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"reminders", reminder.ReminderViewSet, "reminders")
