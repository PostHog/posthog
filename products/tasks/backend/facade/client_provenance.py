from rest_framework.request import Request

from posthog.oauth_provenance import is_interactive_desktop_grant

from products.tasks.backend.models import TaskClientProvenance


def get_task_client_provenance(request: Request) -> TaskClientProvenance | None:
    if is_interactive_desktop_grant(request):
        return TaskClientProvenance.POSTHOG_DESKTOP
    return None
