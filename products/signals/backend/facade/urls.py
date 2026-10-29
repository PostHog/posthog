"""URL patterns that core mounts outside the project router.

Core splices each list into ``posthog/urls.py`` at a fixed position, because the order of
``urlpatterns`` decides which pattern matches first.
"""

from django.urls import URLPattern, path
from django.views.decorators.csrf import csrf_exempt

from products.signals.backend.views import InternalSignalViewSet, SignalUserAutonomyConfigView

user_urlpatterns: list[URLPattern] = [
    path(
        "api/users/<str:user_id>/signal_autonomy/",
        SignalUserAutonomyConfigView.as_view(),
        name="user_signal_autonomy",
    ),
]

internal_urlpatterns: list[URLPattern] = [
    path(
        "api/projects/<str:team_id>/internal/signals/emit",
        csrf_exempt(InternalSignalViewSet.as_view({"post": "emit"})),
    ),
]
