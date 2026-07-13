from posthog.api.routing import RouterRegistry

import products.tasks.backend.presentation.views.api as tasks
import products.tasks.backend.presentation.views.seat_api as seats
import products.tasks.backend.presentation.views.code_home_api as code_home


def register_routes(routers: RouterRegistry) -> None:
    project_tasks_router = routers.projects.register(r"tasks", tasks.TaskViewSet, "project_tasks", ["team_id"])
    project_tasks_router.register(r"runs", tasks.TaskRunViewSet, "project_task_runs", ["team_id", "task_id"])
    routers.projects.register(r"task_automations", tasks.TaskAutomationViewSet, "project_task_automations", ["team_id"])
    routers.projects.register(
        r"sandbox_environments", tasks.SandboxEnvironmentViewSet, "project_sandbox_environments", ["team_id"]
    )
    routers.projects.register(r"code_workflow", code_home.CodeWorkflowViewSet, "project_code_workflow", ["team_id"])
    routers.projects.register(r"code_home", code_home.CodeHomeViewSet, "project_code_home", ["team_id"])
    routers.root.register(r"code/invites", tasks.CodeInviteViewSet, "code_invites")
    routers.root.register(r"seats", seats.SeatViewSet, "seats")
