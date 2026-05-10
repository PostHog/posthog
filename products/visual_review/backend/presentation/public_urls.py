"""URL configuration for unauthenticated visual_review endpoints."""

from django.urls import path

from .public_views import public_artifact_view

urlpatterns = [
    path("artifact/<uuid:artifact_id>", public_artifact_view, name="visual-review-public-artifact"),
]
