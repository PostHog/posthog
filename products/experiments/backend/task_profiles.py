from products.tasks.backend.facade.profiles import Read, TaskProfile

CLEANUP = TaskProfile(
    key="experiments.cleanup",
    origin_product="experiments",
    billing_product="posthog_code",
    read_without_channel=Read.TEAM,
)

PROFILES = (CLEANUP,)
