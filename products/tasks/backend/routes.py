from posthog.api.routing import RouterRegistry

import products.tasks.backend.presentation.views.api as tasks
import products.tasks.backend.presentation.views.loops as loops
import products.tasks.backend.presentation.views.desktop as desktop
import products.tasks.backend.presentation.views.seat_api as seats
import products.tasks.backend.presentation.views.channels_api as channels
import products.tasks.backend.presentation.views.desktop_access as desktop_access
import products.tasks.backend.presentation.views.task_usage_api as task_usage
import products.tasks.backend.presentation.views.sandbox_pricing_api as sandbox_pricing


def register_routes(routers: RouterRegistry) -> None:
    routers.organizations.register(
        r"desktop_beta_terms",
        desktop.DesktopBetaTermsViewSet,
        "organization_desktop_beta_terms",
        ["organization_id"],
    )
    routers.projects.register(r"desktop", desktop_access.DesktopAccessViewSet, "project_desktop", ["team_id"])
    project_tasks_router = routers.projects.register(r"tasks", tasks.TaskViewSet, "project_tasks", ["team_id"])
    project_task_runs_router = project_tasks_router.register(
        r"runs", tasks.TaskRunViewSet, "project_task_runs", ["team_id", "task_id"]
    )
    project_task_runs_router.register(
        r"living_artifacts",
        tasks.TaskRunLivingArtifactViewSet,
        "project_task_run_living_artifacts",
        ["team_id", "task_id", "run_id"],
    )
    project_tasks_router.register(
        r"thread_messages", channels.TaskThreadMessageViewSet, "project_task_thread_messages", ["team_id", "task_id"]
    )
    project_task_channels_router = routers.projects.register(
        r"task_channels", channels.ChannelViewSet, "project_task_channels", ["team_id"]
    )
    project_task_channels_router.register(
        r"feed",
        channels.ChannelFeedMessageViewSet,
        "project_task_channel_feed",
        ["team_id", "channel_id"],
    )
    routers.projects.register(r"task_mentions", channels.TaskMentionViewSet, "project_task_mentions", ["team_id"])
    routers.projects.register(r"task_activity", channels.TaskActivityViewSet, "project_task_activity", ["team_id"])
    routers.projects.register(r"loops", loops.LoopViewSet, "project_loops", ["team_id"])
    routers.projects.register(
        r"sandbox_environments", tasks.SandboxEnvironmentViewSet, "project_sandbox_environments", ["team_id"]
    )
    routers.projects.register(
        r"sandbox_custom_images", tasks.SandboxCustomImageViewSet, "project_sandbox_custom_images", ["team_id"]
    )
    routers.root.register(r"code/invites", tasks.CodeInviteViewSet, "code_invites")
    routers.root.register(
        r"code/sandbox-pricing", sandbox_pricing.SandboxComputePricingViewSet, "sandbox_compute_pricing"
    )
    routers.root.register(r"seats", seats.SeatViewSet, "seats")
    routers.root.register(r"code/internal/task_usage", task_usage.InternalTaskUsageViewSet, "internal_task_usage")
