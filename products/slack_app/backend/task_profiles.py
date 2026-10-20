from products.tasks.backend.facade.profiles import PrAuthorship, TaskProfile

SLACK = TaskProfile(
    key="slack",
    origin_product="slack",
    billing_product="slack_app",
    user_authorable_prs=True,
    default_pr_authorship=PrAuthorship.USER,
)

REPO_SELECTION = TaskProfile(
    key="slack.repo_selection",
    origin_product="slack",
    billing_product="slack_app",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    user_authorable_prs=True,
    default_pr_authorship=PrAuthorship.USER,
)

PROFILES = (SLACK, REPO_SELECTION)
