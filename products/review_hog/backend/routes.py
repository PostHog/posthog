from posthog.api.routing import RouterRegistry

from products.review_hog.backend.api import (
    ReviewBlindSpotsConfigViewSet,
    ReviewHogTriggerViewSet,
    ReviewPerspectiveConfigViewSet,
    ReviewUserSettingsViewSet,
    ReviewValidatorConfigViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    # Unscoped: the trigger resolves team + run user server-side and is gated by a shared secret, so it
    # mounts at /api/review_hog/trigger (no team in the URL) rather than under the project router.
    routers.root.register(r"review_hog", ReviewHogTriggerViewSet, "review_hog")
    # Team-scoped: per-user perspective enablement for the project's reviews (the config UI).
    routers.projects.register(
        r"review_hog/perspectives",
        ReviewPerspectiveConfigViewSet,
        "project_review_hog_perspectives",
        ["team_id"],
    )
    # Team-scoped: per-user selection of the single active review validator (the config UI).
    routers.projects.register(
        r"review_hog/validators",
        ReviewValidatorConfigViewSet,
        "project_review_hog_validators",
        ["team_id"],
    )
    # Team-scoped: per-user selection of the single active blind-spots skill (the config UI).
    routers.projects.register(
        r"review_hog/blind_spots",
        ReviewBlindSpotsConfigViewSet,
        "project_review_hog_blind_spots",
        ["team_id"],
    )
    # Team-scoped: per-user trigger opt-outs + urgency threshold, at review_hog/settings (the viewset
    # has no list/detail routes — only the GET+PATCH "settings" action).
    routers.projects.register(
        r"review_hog",
        ReviewUserSettingsViewSet,
        "project_review_hog_settings",
        ["team_id"],
    )
