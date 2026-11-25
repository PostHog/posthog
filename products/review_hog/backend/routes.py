from posthog.api.routing import RouterRegistry

from products.review_hog.backend.presentation.views import (
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
        r"code_review/perspectives",
        ReviewPerspectiveConfigViewSet,
        "project_code_review_perspectives",
        ["team_id"],
    )
    # Team-scoped: per-user selection of the single active review validator (the config UI).
    routers.projects.register(
        r"code_review/validators",
        ReviewValidatorConfigViewSet,
        "project_code_review_validators",
        ["team_id"],
    )
    # Team-scoped: per-user selection of the single active blind-spots skill (the config UI).
    routers.projects.register(
        r"code_review/blind_spots",
        ReviewBlindSpotsConfigViewSet,
        "project_code_review_blind_spots",
        ["team_id"],
    )
    # Team-scoped: per-user selection of the single active resolution-criteria skill (the config UI).
    routers.projects.register(
        r"code_review/resolution",
        ReviewResolutionConfigViewSet,
        "project_code_review_resolution",
        ["team_id"],
    )
    # Team-scoped: the requesting user's recent reviews (read-only meta for the config UI).
    routers.projects.register(
        r"code_review/reviews",
        ReviewRecentReviewsViewSet,
        "project_code_review_reviews",
        ["team_id"],
    )
    # Team-scoped: the repositories this project has settings for (admins write, members read).
    routers.projects.register(
        r"code_review/repositories",
        ReviewRepositoryViewSet,
        "project_code_review_repositories",
        ["team_id"],
    )
    # Team-scoped: which repositories of each GitHub installation this project reviews.
    routers.projects.register(
        r"code_review/installation_claims",
        ReviewInstallationClaimViewSet,
        "project_code_review_installation_claims",
        ["team_id"],
    )
    # Team-scoped: the requesting user's own choices for single repositories.
    routers.projects.register(
        r"code_review/repository_choices",
        ReviewRepositoryChoiceViewSet,
        "project_code_review_repository_choices",
        ["team_id"],
    )
    # Team-scoped: the project rule and the repository overview, at code_review/project_settings and
    # code_review/repository_overview (the viewset has only those actions).
    routers.projects.register(
        r"code_review",
        ReviewProjectSettingsViewSet,
        "project_code_review_project_settings",
        ["team_id"],
    )
    # Team-scoped: per-user trigger opt-outs + urgency threshold, at code_review/settings (the viewset
    # has no list/detail routes — only the GET+PATCH "settings" action).
    routers.projects.register(
        r"code_review",
        ReviewUserSettingsViewSet,
        "project_code_review_settings",
        ["team_id"],
    )
