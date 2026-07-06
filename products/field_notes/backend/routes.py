from posthog.api.routing import RouterRegistry

from products.field_notes.backend.api import FieldNoteViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"field_notes", FieldNoteViewSet, "environment_field_notes", ["team_id"])
