from products.tasks.backend.facade.profiles import TaskProfile, register_task_profiles

TASK_ANALYSIS = TaskProfile(
    key="task_analysis",
    origin_product="task_analysis",
    billing_product="background_agents",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
)

PROFILES = (TASK_ANALYSIS,)


def register() -> None:
    register_task_profiles(PROFILES)
