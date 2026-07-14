from posthog.api.routing import RouterRegistry

import products.tasks.backend.presentation.views.api as tasks
import products.tasks.backend.presentation.views.seat_api as seats
import products.tasks.backend.presentation.views.channels_api as channels
import products.tasks.backend.presentation.views.code_home_api as code_home


def register_routes(routers: RouterRegistry) -> None:
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
    routers.projects.register(r"task_automations", tasks.TaskAutomationViewSet, "project_task_automations", ["team_id"])
    routers.projects.register(
        r"sandbox_environments", tasks.SandboxEnvironmentViewSet, "project_sandbox_environments", ["team_id"]
    )
    routers.projects.register(
        r"sandbox_custom_images", tasks.SandboxCustomImageViewSet, "project_sandbox_custom_images", ["team_id"]
    )
    routers.projects.register(r"code_workflow", code_home.CodeWorkflowViewSet, "project_code_workflow", ["team_id"])
    routers.projects.register(r"code_home", code_home.CodeHomeViewSet, "project_code_home", ["team_id"])
    routers.root.register(r"code/invites", tasks.CodeInviteViewSet, "code_invites")
    routers.root.register(r"seats", seats.SeatViewSet, "seats")
