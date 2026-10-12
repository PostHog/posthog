from posthog.api.routing import RouterRegistry

from products.review_hog.backend.api import (
    ReviewBlindSpotsConfigViewSet,
    ReviewInstallationClaimViewSet,
    ReviewPerspectiveConfigViewSet,
    ReviewProjectSettingsViewSet,
    ReviewRecentReviewsViewSet,
    ReviewRepositoryChoiceViewSet,
    ReviewRepositoryViewSet,
    ReviewResolutionConfigViewSet,
    ReviewUserSettingsViewSet,
    ReviewValidatorConfigViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
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
    # Team-scoped: per-user selection of the single active resolution-criteria skill (the config UI).
    routers.projects.register(
        r"review_hog/resolution",
        ReviewResolutionConfigViewSet,
        "project_review_hog_resolution",
        ["team_id"],
    )
    # Team-scoped: the requesting user's recent reviews (read-only meta for the config UI).
    routers.projects.register(
        r"review_hog/reviews",
        ReviewRecentReviewsViewSet,
        "project_review_hog_reviews",
        ["team_id"],
    )
    # Team-scoped: the repositories this project has settings for (admins write, members read).
    routers.projects.register(
        r"review_hog/repositories",
        ReviewRepositoryViewSet,
        "project_review_hog_repositories",
        ["team_id"],
    )
    # Team-scoped: which repositories of each GitHub installation this project reviews.
    routers.projects.register(
        r"review_hog/installation_claims",
        ReviewInstallationClaimViewSet,
        "project_review_hog_installation_claims",
        ["team_id"],
    )
    # Team-scoped: the requesting user's own choices for single repositories.
    routers.projects.register(
        r"review_hog/repository_choices",
        ReviewRepositoryChoiceViewSet,
        "project_review_hog_repository_choices",
        ["team_id"],
    )
    # Team-scoped: the project rule and the repository overview, at review_hog/project_settings and
    # review_hog/repository_overview (the viewset has only those actions).
    routers.projects.register(
        r"review_hog",
        ReviewProjectSettingsViewSet,
        "project_review_hog_project_settings",
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
