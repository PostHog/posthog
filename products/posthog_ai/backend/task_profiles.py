from products.tasks.backend.facade.profiles import OAuthApp, TaskProfile, WarmPolicy, WarmQuota

CHAT_WARM_POLICY = WarmPolicy(quota=WarmQuota.AI_CREDITS, per_user_cap=2, per_org_cap=10)

POSTHOG_AI = TaskProfile(
    key="posthog_ai",
    origin_product="posthog_ai",
    billing_product="posthog_ai",
    public=True,
    warm=CHAT_WARM_POLICY,
    oauth_app=OAuthApp.POSTHOG_AI,
    user_authorable_prs=True,
    # Chat-shaped: a late follow-up rebuilds the session from the run log, so holding idle compute isn't worth it.
    idle_minutes=10,
)

IMPORTED = TaskProfile(
    key="posthog_ai.imported",
    origin_product="posthog_ai",
    billing_product="posthog_ai",
    warm=CHAT_WARM_POLICY,
    oauth_app=OAuthApp.POSTHOG_AI,
    user_authorable_prs=True,
    idle_minutes=10,
)

IMPORTED_INTERNAL = TaskProfile(
    key="posthog_ai.imported_internal",
    origin_product="posthog_ai",
    billing_product="posthog_ai",
    warm=CHAT_WARM_POLICY,
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    oauth_app=OAuthApp.POSTHOG_AI,
    user_authorable_prs=True,
    idle_minutes=10,
)

PROFILES = (POSTHOG_AI, IMPORTED, IMPORTED_INTERNAL)
