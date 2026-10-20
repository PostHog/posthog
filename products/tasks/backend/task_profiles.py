from products.tasks.backend.facade.profiles import (
    DrivePolicy,
    PrAuthorship,
    Read,
    TaskProfile,
    WarmPolicy,
    WarmQuota,
    register_task_profiles,
)

USER = TaskProfile(
    key="user",
    origin_product="user_created",
    billing_product="posthog_code",
    public=True,
    warm=WarmPolicy(quota=WarmQuota.NONE, per_user_cap=10, per_org_cap=100, feature_flag="tasks-prewarm-sandbox"),
    user_authorable_prs=True,
    default_pr_authorship=PrAuthorship.USER,
    idle_minutes=60,
    max_wake_minutes=None,
    bills_compute=True,
)

SPACE_SETUP = TaskProfile(
    key="space_setup",
    origin_product="space_setup",
    billing_product="posthog_code",
    idle_minutes=60,
    max_wake_minutes=None,
    bills_compute=True,
)

IMAGE_BUILDER = TaskProfile(
    key="image_builder",
    origin_product="image_builder",
    billing_product="posthog_code",
    idle_minutes=60,
    max_wake_minutes=None,
)

TASK_ANALYSIS = TaskProfile(
    key="task_analysis",
    origin_product="task_analysis",
    billing_product="background_agents",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
)

WORKFLOW = TaskProfile(
    key="workflow",
    origin_product="workflow",
    billing_product="workflows",
    source_kind="hog_flow",
    read_without_channel=Read.TEAM,
    drive=DrivePolicy.AUDIENCE,
    mcp_agent="workflow",
)

WIZARD = TaskProfile(
    key="wizard",
    origin_product="onboarding",
    billing_product="onboarding",
    read_without_channel=Read.TEAM,
    drive=DrivePolicy.AUDIENCE,
)

HOGDESK = TaskProfile(
    key="hogdesk",
    origin_product="hogdesk",
    billing_product="posthog_code",
    public=True,
    read_without_channel=Read.TEAM,
    drive=DrivePolicy.AUDIENCE,
)

LOOP = TaskProfile(
    key="loop",
    origin_product="loop",
    billing_product="posthog_code",
    public=True,
    mcp_scopes="read_only",
)

ERROR_TRACKING = TaskProfile(
    key="error_tracking", origin_product="error_tracking", billing_product="posthog_code", public=True
)
EVAL_CLUSTERS = TaskProfile(
    key="eval_clusters", origin_product="eval_clusters", billing_product="posthog_code", public=True
)
SUPPORT_QUEUE = TaskProfile(
    key="support_queue", origin_product="support_queue", billing_product="posthog_code", public=True
)
SESSION_SUMMARIES = TaskProfile(
    key="session_summaries", origin_product="session_summaries", billing_product="posthog_code", public=True
)
MCP_ANALYTICS = TaskProfile(
    key="mcp_analytics", origin_product="mcp_analytics", billing_product="posthog_code", public=True
)

LEGACY = TaskProfile(key="legacy", origin_product="", billing_product="posthog_code")
LEGACY_INTERNAL = TaskProfile(
    key="legacy.internal",
    origin_product="",
    billing_product="background_agents",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
)

PROFILES = (
    USER,
    SPACE_SETUP,
    IMAGE_BUILDER,
    TASK_ANALYSIS,
    WORKFLOW,
    WIZARD,
    HOGDESK,
    LOOP,
    ERROR_TRACKING,
    EVAL_CLUSTERS,
    SUPPORT_QUEUE,
    SESSION_SUMMARIES,
    MCP_ANALYTICS,
    LEGACY,
    LEGACY_INTERNAL,
)


def register() -> None:
    register_task_profiles(PROFILES)
