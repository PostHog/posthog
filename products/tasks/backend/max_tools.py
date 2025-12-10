from typing import Any

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.storage import object_storage

from ee.hogai.tool import MaxTool

from .models import Task, TaskRun
from .temporal.client import execute_task_processing_workflow_async


class CreateTaskArgs(BaseModel):
    title: str = Field(description="Title of the task")
    description: str = Field(description="Detailed description of what the task should accomplish")
    repository: str = Field(description="Repository in format 'org/repo' (e.g., 'posthog/posthog-js')")
    run: bool = Field(default=True, description="Whether to immediately run the task after creation")


class RunTaskArgs(BaseModel):
    task_id: str = Field(description="UUID of the task to run")


class GetTaskRunArgs(BaseModel):
    task_id: str = Field(description="UUID of the task")
    run_id: str | None = Field(default=None, description="UUID of a specific run. If not provided, uses the latest run")


class GetTaskRunLogsArgs(BaseModel):
    task_id: str = Field(description="UUID of the task")
    run_id: str | None = Field(default=None, description="UUID of a specific run. If not provided, uses the latest run")


class ListTasksArgs(BaseModel):
    origin_product: str | None = Field(
        default=None, description="Filter by origin product (e.g., 'error_tracking', 'user_created')"
    )
    repository: str | None = Field(default=None, description="Filter by repository (e.g., 'posthog/posthog-js')")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of tasks to return")


class ListTaskRunsArgs(BaseModel):
    task_id: str = Field(description="UUID of the task to list runs for")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of runs to return")


class ListRepositoriesArgs(BaseModel):
    search: str | None = Field(default=None, description="Optional search term to filter repositories by name")


class CreateTaskTool(MaxTool):
    name: str = "create_task"
    description: str = """
Create a new task in the Tasks product.

Use this tool when the user wants to:
- Create a new coding task for an AI agent to execute
- Set up a task to fix an issue, implement a feature, or make changes to a repository

By default, the task will be created and immediately executed. Set run=false to create without executing.
    """.strip()
    args_schema: type[BaseModel] = CreateTaskArgs

    async def _arun_impl(
        self, title: str, description: str, repository: str, run: bool = True
    ) -> tuple[str, dict[str, Any]]:
        from posthog.models.integration import Integration

        @sync_to_async
        def create_task_and_maybe_run():
            github_integration = Integration.objects.filter(team=self._team, kind="github").first()

            task = Task.objects.create(
                team=self._team,
                created_by=self._user,
                title=title,
                description=description,
                origin_product=Task.OriginProduct.USER_CREATED,
                repository=repository,
                github_integration=github_integration,
            )

            task_run = None
            if run:
                task_run = task.create_run()

            task_url = f"/project/{self._team.project.id}/tasks/{task.id}"
            if task_run:
                task_url = f"{task_url}?runId={task_run.id}"

            result = {
                "task_id": str(task.id),
                "slug": task.slug,
                "title": task.title,
                "url": task_url,
                "team_id": task.team.id,
            }

            if task_run:
                result["latest_run"] = {
                    "run_id": str(task_run.id),
                    "status": task_run.status,
                    "status_display": task_run.get_status_display(),
                }

            return result

        result = await create_task_and_maybe_run()

        if run and "latest_run" in result:
            slack_thread_context = (self._config.get("configurable") or {}).get("slack_thread_context")

            await execute_task_processing_workflow_async(
                task_id=result["task_id"],
                run_id=result["latest_run"]["run_id"],
                team_id=result["team_id"],
                user_id=self._user.id,
                slack_thread_context=slack_thread_context,
            )

            return (
                f"Created and started task '{result['title']}' (ID: {result['task_id']}).\n"
                f"Run ID: {result['latest_run']['run_id']}\n"
                f"View at {result['url']}",
                result,
            )

        return (
            f"Created task '{result['title']}' (ID: {result['task_id']}). "
            f"Use the run_task tool to execute it. View at {result['url']}",
            result,
        )


class RunTaskTool(MaxTool):
    name: str = "run_task"
    description: str = """
Trigger execution of an existing task.

Use this tool when the user wants to:
- Start a task that was previously created
- Re-run a task after it failed or was cancelled
- Execute a task to make changes to a repository
    """.strip()
    args_schema: type[BaseModel] = RunTaskArgs

    async def _arun_impl(self, task_id: str) -> tuple[str, dict[str, Any]]:
        @sync_to_async
        def get_task_and_create_run():
            task = Task.objects.filter(id=task_id, team=self._team, deleted=False).first()

            if not task:
                return None

            task_run = task.create_run()
            task_url = f"/project/{task.team.project.id}/tasks/{task.id}?runId={task_run.id}"
            return {
                "task_id": str(task.id),
                "run_id": str(task_run.id),
                "slug": task.slug,
                "title": task.title,
                "team_id": task.team.id,
                "url": task_url,
            }

        result = await get_task_and_create_run()

        if not result:
            return f"Task with ID {task_id} not found", {"error": "not_found"}

        # Extract slack thread context from config if available
        slack_thread_context = (self._config.get("configurable") or {}).get("slack_thread_context")

        await execute_task_processing_workflow_async(
            task_id=result["task_id"],
            run_id=result["run_id"],
            team_id=result["team_id"],
            user_id=self._user.id,
            slack_thread_context=slack_thread_context,
        )

        return (
            f"Started execution of task '{result['title']}' ({result['slug']}).\n"
            f"Run ID: {result['run_id']}\n"
            f"View at {result['url']}",
            result,
        )


class GetTaskRunTool(MaxTool):
    name: str = "get_task_run"
    description: str = """
Get the current status of a task run, including stage, status, branch, and any errors.

Use this tool when the user wants to:
- Check if a task is still running
- See if a task completed successfully or failed
- Get the current stage of a task execution (research, plan, build, etc.)
    """.strip()
    args_schema: type[BaseModel] = GetTaskRunArgs

    async def _arun_impl(self, task_id: str, run_id: str | None = None) -> tuple[str, dict[str, Any]]:
        @sync_to_async
        def get_task_and_run():
            task = Task.objects.filter(id=task_id, team=self._team, deleted=False).first()

            if not task:
                return {"error": "not_found", "task_id": task_id}

            if run_id:
                task_run = TaskRun.objects.filter(id=run_id, task=task).first()
            else:
                task_run = task.latest_run

            task_info = {
                "id": str(task.id),
                "slug": task.slug,
                "title": task.title,
                "repository": task.repository,
            }

            if not task_run:
                return {"error": "no_runs" if not run_id else "run_not_found", "task_info": task_info, "run_id": run_id}

            return {
                "task_info": task_info,
                "run": {
                    "run_id": str(task_run.id),
                    "status": task_run.status,
                    "status_display": task_run.get_status_display(),
                    "stage": task_run.stage,
                    "branch": task_run.branch,
                    "created_at": task_run.created_at.isoformat(),
                    "completed_at": task_run.completed_at.isoformat() if task_run.completed_at else None,
                    "error_message": task_run.error_message,
                    "output": task_run.output,
                },
            }

        result = await get_task_and_run()

        if result.get("error") == "not_found":
            return f"Task with ID {task_id} not found", {"error": "not_found"}

        task_info = result.get("task_info")
        if result.get("error") == "run_not_found":
            return f"Run with ID {result['run_id']} not found for task {task_id}", {"error": "run_not_found"}
        if result.get("error") == "no_runs":
            return f"Task '{task_info['title']}' has no runs yet", {"error": "no_runs"}

        run = result["run"]
        status_info: dict[str, Any] = {
            "task_id": task_info["id"],
            "slug": task_info["slug"],
            "title": task_info["title"],
            "repository": task_info["repository"],
            "run": run,
        }

        message = f"Task '{task_info['title']}' ({task_info['slug']})\nStatus: {run['status_display']}\n"
        if run["stage"]:
            message += f"Current stage: {run['stage']}\n"
        if run["branch"]:
            message += f"Branch: {run['branch']}\n"
        if run["error_message"]:
            message += f"Error: {run['error_message']}\n"
        if run["output"]:
            message += f"Output: {run['output']}\n"

        return message, status_info


class GetTaskRunLogsTool(MaxTool):
    name: str = "get_task_run_logs"
    description: str = """
Get the execution logs from a task run.

Use this tool when the user wants to:
- See what happened during a task execution
- Debug why a task failed
- Review the steps the AI agent took
    """.strip()
    args_schema: type[BaseModel] = GetTaskRunLogsArgs

    async def _arun_impl(self, task_id: str, run_id: str | None = None) -> tuple[str, dict[str, Any]]:
        @sync_to_async
        def get_task_and_run():
            task = Task.objects.filter(id=task_id, team=self._team, deleted=False).first()

            if not task:
                return {"error": "not_found"}

            if run_id:
                task_run = TaskRun.objects.filter(id=run_id, task=task).first()
            else:
                task_run = task.latest_run

            if not task_run:
                return {
                    "error": "no_runs" if not run_id else "run_not_found",
                    "task_title": task.title,
                    "run_id": run_id,
                }

            return {
                "task_id": str(task.id),
                "task_title": task.title,
                "run_id": str(task_run.id),
                "status": task_run.status,
                "status_display": task_run.get_status_display(),
                "log_url": task_run.log_url,
            }

        result = await get_task_and_run()

        if result.get("error") == "not_found":
            return f"Task with ID {task_id} not found", {"error": "not_found"}

        if result.get("error") == "run_not_found":
            return f"Run with ID {result['run_id']} not found for task {task_id}", {"error": "run_not_found"}
        if result.get("error") == "no_runs":
            return f"Task '{result['task_title']}' has no runs yet", {"error": "no_runs"}

        presigned_url = object_storage.get_presigned_url(result["log_url"], expiration=3600)

        if not presigned_url:
            return "Unable to generate log download URL", {"error": "presign_failed"}

        return (
            f"Logs for task '{result['task_title']}' run {result['run_id']} (status: {result['status_display']}).\n"
            f"Download logs from: {presigned_url}\n"
            f"(URL expires in 1 hour)",
            {
                "task_id": result["task_id"],
                "run_id": result["run_id"],
                "status": result["status"],
                "log_url": presigned_url,
                "expires_in": 3600,
            },
        )


class ListTasksTool(MaxTool):
    name: str = "list_tasks"
    description: str = """
List tasks in the current project with optional filtering.

Use this tool when the user wants to:
- See all tasks in the project
- Find tasks for a specific repository
- Filter tasks by their origin (error_tracking, user_created, etc.)
    """.strip()
    args_schema: type[BaseModel] = ListTasksArgs

    async def _arun_impl(
        self, origin_product: str | None = None, repository: str | None = None, limit: int = 10
    ) -> tuple[str, dict[str, Any]]:
        @sync_to_async
        def query_tasks():
            qs = Task.objects.filter(team=self._team, deleted=False).order_by("-created_at")

            if origin_product:
                qs = qs.filter(origin_product=origin_product)

            if repository:
                repo_str = repository.strip().lower()
                if "/" in repo_str:
                    qs = qs.filter(repository__iexact=repo_str)
                else:
                    qs = qs.filter(repository__iendswith=f"/{repo_str}")

            tasks = list(qs.prefetch_related("runs")[:limit])

            task_list = []
            lines = [f"Found {len(tasks)} task(s):\n"] if tasks else []

            for task in tasks:
                latest_run = task.latest_run
                status = latest_run.get_status_display() if latest_run else "Not run"

                lines.append(f"- {task.slug} (ID: {task.id}): {task.title}")
                lines.append(f"  Status: {status} | Repository: {task.repository or 'N/A'}")

                task_list.append(
                    {
                        "id": str(task.id),
                        "slug": task.slug,
                        "title": task.title,
                        "repository": task.repository,
                        "origin_product": task.origin_product,
                        "status": latest_run.status if latest_run else None,
                    }
                )

            return {"tasks": task_list, "lines": lines}

        result = await query_tasks()

        if not result["tasks"]:
            return "No tasks found matching the criteria", {"tasks": []}

        return "\n".join(result["lines"]), {"tasks": result["tasks"]}


class ListTaskRunsTool(MaxTool):
    name: str = "list_task_runs"
    description: str = """
List all runs for a specific task.

Use this tool when the user wants to:
- See the history of runs for a task
- Find a specific run by looking at the list
- Compare different runs of the same task
    """.strip()
    args_schema: type[BaseModel] = ListTaskRunsArgs

    async def _arun_impl(self, task_id: str, limit: int = 10) -> tuple[str, dict[str, Any]]:
        @sync_to_async
        def get_task_and_runs():
            task = Task.objects.filter(id=task_id, team=self._team, deleted=False).first()

            if not task:
                return {"error": "not_found"}

            runs = list(TaskRun.objects.filter(task=task).order_by("-created_at")[:limit])

            task_info = {
                "id": str(task.id),
                "slug": task.slug,
                "title": task.title,
            }

            run_list = []
            lines = [f"Task '{task.title}' ({task.slug}) - {len(runs)} run(s):\n"] if runs else []

            for run in runs:
                lines.append(f"- Run ID: {run.id}")
                lines.append(f"  Status: {run.get_status_display()} | Stage: {run.stage or 'N/A'}")
                lines.append(f"  Created: {run.created_at.isoformat()}")
                if run.error_message:
                    truncated = run.error_message[:100]
                    suffix = "..." if len(run.error_message) > 100 else ""
                    lines.append(f"  Error: {truncated}{suffix}")

                run_list.append(
                    {
                        "run_id": str(run.id),
                        "status": run.status,
                        "stage": run.stage,
                        "branch": run.branch,
                        "created_at": run.created_at.isoformat(),
                        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                        "error_message": run.error_message,
                    }
                )

            return {"task_info": task_info, "runs": run_list, "lines": lines}

        result = await get_task_and_runs()

        if result.get("error") == "not_found":
            return f"Task with ID {task_id} not found", {"error": "not_found"}

        task_info = result["task_info"]
        run_list = result["runs"]
        lines = result["lines"]

        if not run_list:
            return (
                f"Task '{task_info['title']}' ({task_info['slug']}) has no runs yet",
                {"task_id": task_info["id"], "runs": []},
            )

        return "\n".join(lines), {"task_id": task_info["id"], "slug": task_info["slug"], "runs": run_list}


class ListRepositoriesTool(MaxTool):
    name: str = "list_repositories"
    description: str = """
List available GitHub repositories that can be used for tasks.

Use this tool when the user wants to:
- See which repositories are available for creating tasks
- Find a specific repository by name
- Check if a repository is connected via GitHub integration
    """.strip()
    args_schema: type[BaseModel] = ListRepositoriesArgs

    async def _arun_impl(self, search: str | None = None) -> tuple[str, dict[str, Any]]:
        from posthog.models.integration import GitHubIntegration, Integration

        @sync_to_async
        def get_repositories():
            integrations = Integration.objects.filter(team=self._team, kind="github")

            all_repos: list[dict[str, str]] = []

            for integration in integrations:
                try:
                    github = GitHubIntegration(integration)
                    org = github.organization()
                    repo_names = github.list_repositories()

                    for repo_name in repo_names:
                        full_name = f"{org}/{repo_name}"
                        if search:
                            if search.lower() not in repo_name.lower():
                                continue
                        all_repos.append(
                            {
                                "repository": full_name,
                                "organization": org,
                                "name": repo_name,
                            }
                        )
                except Exception:
                    continue

            return all_repos

        repos = await get_repositories()

        if not repos:
            if search:
                return f"No repositories found matching '{search}'", {"repositories": []}
            settings_url = "/settings/project-integrations"
            return (
                f"No GitHub repositories available. Please connect a GitHub integration in Settings: {settings_url}",
                {"repositories": [], "settings_url": settings_url},
            )

        lines = [f"Found {len(repos)} repository(ies):\n"]
        for repo in repos:
            lines.append(f"- {repo['repository']}")

        return "\n".join(lines), {"repositories": repos}
