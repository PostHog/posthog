from products.tasks.backend.facade.profiles import GithubResolution, OAuthApp, TaskProfile

DASHBOARD_IMPORT = TaskProfile(
    key="metrics.dashboard_import",
    origin_product="metrics_import",
    billing_product="posthog_ai",
    listed=False,
    api_visible=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    oauth_app=OAuthApp.POSTHOG_AI,
    github_resolution=GithubResolution.WITH_REPOSITORY,
)

PROFILES = (DASHBOARD_IMPORT,)
