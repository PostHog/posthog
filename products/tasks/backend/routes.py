from posthog.api.routing import RouterRegistry

import products.tasks.backend.api as tasks
import products.tasks.backend.seat_api as seats


def register_routes(routers: RouterRegistry) -> None:
    project_tasks_router = routers.projects.register(r"tasks", tasks.TaskViewSet, "project_tasks", ["team_id"])
    project_tasks_router.register(r"runs", tasks.TaskRunViewSet, "project_task_runs", ["team_id", "task_id"])
    routers.projects.register(r"task_automations", tasks.TaskAutomationViewSet, "project_task_automations", ["team_id"])
    routers.projects.register(
        r"sandbox_environments", tasks.SandboxEnvironmentViewSet, "project_sandbox_environments", ["team_id"]
    )
    routers.root.register(r"code/invites", tasks.CodeInviteViewSet, "code_invites")
    routers.root.register(r"seats", seats.SeatViewSet, "seats")
