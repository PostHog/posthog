from typing import TYPE_CHECKING

from posthog.event_usage import EventSource, get_event_source

if TYPE_CHECKING:
    from rest_framework.request import Request


def reusable_widget_origin(request: "Request", *, automatic: bool = False) -> str:
    if automatic:
        return "auto_attach"
    source = get_event_source(request)
    return "ui" if source == EventSource.WEB else source.value
