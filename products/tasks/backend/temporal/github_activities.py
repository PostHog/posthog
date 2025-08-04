"""
GitHub integration activities for issue tracker workflows using the main GitHub integration system.
"""

import asyncio
import os
import tempfile
import shutil
from pathlib import Path
from typing import Any, Optional

import temporalio

from posthog.temporal.common.logger import bind_contextvars, get_logger
from posthog.sync import database_sync_to_async
from .inputs import TaskProcessingInputs, CreatePRInputs, CommitChangesInputs

logger = get_logger(__name__)


@temporalio.activity.defn
async def create_branch_using_integration_activity(inputs: TaskProcessingInputs) -> dict[str, Any]:
    """
    Create a branch using the main GitHub integration system.

    Returns:
        Dict with branch creation results
    """
    bind_contextvars(task_id=inputs.task_id, team_id=inputs.team_id, activity="create_branch_using_integration")

    logger.info(f"Creating branch using main GitHub integration for issue {inputs.task_id}")

    try:
        # Import models inside activity
        from django.apps import apps
        from posthog.models.integration import Integration, GitHubIntegration

        Task = apps.get_model("tasks", "Task")

        # Get the issue
        task = await database_sync_to_async(Task.objects.select_related("team", "github_integration").get)(
            id=inputs.task_id, team_id=inputs.team_id
        )

        # Get the specific GitHub integration configured for this issue
        if task.github_integration:
            integration = task.github_integration
        else:
            # Fallback to team's first GitHub integration
            integration = await database_sync_to_async(
                lambda: Integration.objects.filter(team_id=inputs.team_id, kind="github").first()
            )()

        if not integration:
            return {"success": False, "error": "No GitHub integration found for this team"}

        github_integration = GitHubIntegration(integration)

        # Check if token needs refresh
        if github_integration.access_token_expired():
            await database_sync_to_async(github_integration.refresh_access_token)()

        # Get the specific repository configured for this issue
        repository_config = task.repository_config
        if (
            not repository_config
            or not repository_config.get("organization")
            or not repository_config.get("repository")
        ):
            return {
                "success": False,
                "error": "No repository configured for this task. Please configure a repository in the task settings.",
            }

        organization = repository_config["organization"]
        repository_name = repository_config["repository"]
        repository = f"{organization}/{repository_name}"

        # Generate branch name based on issue
        branch_name = f"task-{task.id}-{task.title.lower().replace(' ', '-').replace('_', '-')[:50]}"

        # Check if branch already exists
        branch_info = await database_sync_to_async(github_integration.get_branch_info)(repository, branch_name)

        if branch_info.get("success") and branch_info.get("exists"):
            logger.info(f"Branch {branch_name} already exists")
            return {
                "success": True,
                "branch_name": branch_name,
                "repository": repository,
                "branch_exists": True,
                "commit_sha": branch_info.get("commit_sha"),
            }

        # Create new branch
        result = await database_sync_to_async(github_integration.create_branch)(repository, branch_name)

        if result.get("success"):
            logger.info(f"Successfully created branch {branch_name}")

            # Update issue with branch information
            await database_sync_to_async(Task.objects.filter(id=inputs.task_id).update)(github_branch=branch_name)

            return {
                "success": True,
                "branch_name": branch_name,
                "repository": repository,
                "branch_exists": False,
                "sha": result.get("sha"),
                "ref": result.get("ref"),
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to create branch")}

    except Exception as e:
        logger.exception(f"Error creating branch using integration: {str(e)}")
        return {"success": False, "error": f"Failed to create branch: {str(e)}"}


@temporalio.activity.defn
async def create_pr_using_integration_activity(inputs: CreatePRInputs) -> dict[str, Any]:
    """
    Create a pull request using the main GitHub integration system.

    Args:
        inputs: CreatePRInputs containing issue processing inputs and branch name

    Returns:
        Dict with PR creation results
    """
    issue_inputs = inputs.issue_processing_inputs
    branch_name = inputs.branch_name

    bind_contextvars(task_id=issue_inputs.task_id, team_id=issue_inputs.team_id, activity="create_pr_using_integration")

    logger.info(f"Creating PR using main GitHub integration for issue {issue_inputs.task_id}")

    try:
        # Import models inside activity
        from django.apps import apps
        from posthog.models.integration import Integration, GitHubIntegration

        Task = apps.get_model("tasks", "Task")

        # Get the issue
        task = await database_sync_to_async(Task.objects.select_related("team", "github_integration").get)(
            id=issue_inputs.task_id, team_id=issue_inputs.team_id
        )

        # Get the specific GitHub integration configured for this issue
        if task.github_integration:
            integration = task.github_integration
        else:
            # Fallback to team's first GitHub integration
            integration = await database_sync_to_async(
                lambda: Integration.objects.filter(team_id=issue_inputs.team_id, kind="github").first()
            )()

        if not integration:
            return {"success": False, "error": "No GitHub integration found for this team"}

        github_integration = GitHubIntegration(integration)

        # Check if token needs refresh
        if github_integration.access_token_expired():
            await database_sync_to_async(github_integration.refresh_access_token)()

        # Get the specific repository configured for this issue
        repository_config = task.repository_config
        if (
            not repository_config
            or not repository_config.get("organization")
            or not repository_config.get("repository")
        ):
            return {
                "success": False,
                "error": "No repository configured for this task. Please configure a repository in the task settings.",
            }

        organization = repository_config["organization"]
        repository_name = repository_config["repository"]
        repository = f"{organization}/{repository_name}"

        # Create PR title and body
        pr_title = f"Fix task: {task.title}"
        pr_body = f"""
## Task: {task.title}

**Task ID:** {task.id}
**Status:** {task.status}
**Priority:** {getattr(task, 'priority', 'N/A')}

### Description
{task.description or 'No description provided'}

---
*This PR was automatically created by PostHog Issue Tracker*
        """.strip()

        # Create the pull request
        result = await database_sync_to_async(github_integration.create_pull_request)(
            repository=repository, title=pr_title, body=pr_body, head_branch=branch_name
        )

        if result.get("success"):
            logger.info(f"Successfully created PR #{result['pr_number']}")

            # Update issue with PR information
            await database_sync_to_async(Task.objects.filter(id=issue_inputs.task_id).update)(
                github_pr_url=result.get("pr_url")
            )

            return {
                "success": True,
                "pr_number": result.get("pr_number"),
                "pr_url": result.get("pr_url"),
                "pr_id": result.get("pr_id"),
                "state": result.get("state"),
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to create pull request")}

    except Exception as e:
        logger.exception(f"Error creating PR using integration: {str(e)}")
        return {"success": False, "error": f"Failed to create PR: {str(e)}"}


@temporalio.activity.defn
async def commit_changes_using_integration_activity(inputs: CommitChangesInputs) -> dict[str, Any]:
    """
    Commit file changes using the main GitHub integration system.

    Args:
        inputs: CommitChangesInputs containing issue processing inputs, branch name, and file changes

    Returns:
        Dict with commit results
    """
    issue_inputs = inputs.issue_processing_inputs
    branch_name = inputs.branch_name
    file_changes = inputs.file_changes

    bind_contextvars(
        task_id=issue_inputs.task_id, team_id=issue_inputs.team_id, activity="commit_changes_using_integration"
    )

    logger.info(f"Committing changes using main GitHub integration for issue {issue_inputs.task_id}")

    try:
        # Import models inside activity
        from django.apps import apps
        from posthog.models.integration import Integration, GitHubIntegration

        Task = apps.get_model("tasks", "Task")

        # Get the task to access the specific GitHub integration
        task = await database_sync_to_async(Task.objects.select_related("github_integration").get)(
            id=issue_inputs.task_id, team_id=issue_inputs.team_id
        )

        # Get the specific GitHub integration configured for this issue
        if task.github_integration:
            integration = task.github_integration
        else:
            # Fallback to team's first GitHub integration
            integration = await database_sync_to_async(
                lambda: Integration.objects.filter(team_id=issue_inputs.team_id, kind="github").first()
            )()

        if not integration:
            return {"success": False, "error": "No GitHub integration found for this team"}

        github_integration = GitHubIntegration(integration)

        # Check if token needs refresh
        if github_integration.access_token_expired():
            await database_sync_to_async(github_integration.refresh_access_token)()

        # Get the specific repository configured for this issue
        repository_config = task.repository_config
        if (
            not repository_config
            or not repository_config.get("organization")
            or not repository_config.get("repository")
        ):
            return {
                "success": False,
                "error": "No repository configured for this task. Please configure a repository in the task settings.",
            }

        organization = repository_config["organization"]
        repository_name = repository_config["repository"]
        repository = f"{organization}/{repository_name}"

        committed_files = []

        # Process each file change
        for file_change in file_changes:
            file_path = file_change.get("path")
            content = file_change.get("content")
            message = file_change.get("message", f"Update {file_path} for issue #{issue_inputs.task_id}")

            if not file_path or content is None:
                logger.warning(f"Skipping invalid file change: {file_change}")
                continue

            # Update/create the file
            result = await database_sync_to_async(github_integration.update_file)(
                repository=repository, file_path=file_path, content=content, commit_message=message, branch=branch_name
            )

            if result.get("success"):
                committed_files.append(
                    {
                        "path": file_path,
                        "commit_sha": result.get("commit_sha"),
                        "file_sha": result.get("file_sha"),
                        "html_url": result.get("html_url"),
                    }
                )
                logger.info(f"Successfully committed file {file_path}")
            else:
                logger.error(f"Failed to commit file {file_path}: {result.get('error')}")
                return {
                    "success": False,
                    "error": f"Failed to commit file {file_path}: {result.get('error')}",
                    "committed_files": committed_files,
                }

        return {"success": True, "committed_files": committed_files, "total_files": len(committed_files)}

    except Exception as e:
        logger.exception(f"Error committing changes using integration: {str(e)}")
        return {"success": False, "error": f"Failed to commit changes: {str(e)}"}


@temporalio.activity.defn
async def validate_github_integration_activity(inputs: TaskProcessingInputs) -> dict[str, Any]:
    """
    Validate GitHub integration and repository access using the main integration system.

    Returns:
        Dict with validation results and repository information
    """
    bind_contextvars(task_id=inputs.task_id, team_id=inputs.team_id, activity="validate_github_integration")

    logger.info(f"Validating GitHub integration for team {inputs.team_id}")

    try:
        # Import models inside activity
        from django.apps import apps
        from posthog.models.integration import Integration, GitHubIntegration

        Task = apps.get_model("tasks", "Task")

        # Get the task to access the specific GitHub integration
        task = await database_sync_to_async(Task.objects.select_related("github_integration").get)(
            id=inputs.task_id, team_id=inputs.team_id
        )

        # Get the specific GitHub integration configured for this issue
        if task.github_integration:
            integration = task.github_integration
        else:
            # Fallback to team's first GitHub integration
            integration = await database_sync_to_async(
                lambda: Integration.objects.filter(team_id=inputs.team_id, kind="github").first()
            )()

        if not integration:
            return {"success": False, "error": "No GitHub integration configured for this team"}

        github_integration = GitHubIntegration(integration)

        # Check if token needs refresh
        if github_integration.access_token_expired():
            await database_sync_to_async(github_integration.refresh_access_token)()

        # Get repositories available to this integration
        repositories = await database_sync_to_async(github_integration.list_repositories)()
        if not repositories:
            return {"success": False, "error": "No repositories available in GitHub integration"}

        logger.info(f"GitHub integration validated successfully. Available repositories: {len(repositories)}")

        return {
            "success": True,
            "repositories": repositories,
            "integration": {
                "display_name": integration.display_name,
                "organization": github_integration.organization(),
                "installation_id": integration.integration_id,
            },
        }

    except Exception as e:
        logger.exception(f"Error validating GitHub integration: {str(e)}")
        return {"success": False, "error": f"Validation failed: {str(e)}"}


@temporalio.activity.defn
async def clone_repo_and_create_branch_activity(inputs: TaskProcessingInputs) -> dict[str, Any]:
    """
    Clone the GitHub repository and create a new branch for the issue using the main GitHub integration.

    Args:
        inputs: Issue processing inputs

    Returns:
        Dict with repo_path, branch_name, and status information
    """
    bind_contextvars(task_id=inputs.task_id, team_id=inputs.team_id, activity="clone_repo_and_create_branch")

    logger.info(f"Starting GitHub repo clone and branch creation for issue {inputs.task_id}")

    try:
        # Import models inside activity
        from django.apps import apps
        from posthog.models.integration import Integration, GitHubIntegration

        Task = apps.get_model("tasks", "Task")

        # Get the issue
        task = await database_sync_to_async(Task.objects.select_related("team", "github_integration").get)(
            id=inputs.task_id, team_id=inputs.team_id
        )

        # Get the specific GitHub integration configured for this issue
        if task.github_integration:
            integration = task.github_integration
        else:
            # Fallback to team's first GitHub integration
            integration = await database_sync_to_async(
                lambda: Integration.objects.filter(team_id=inputs.team_id, kind="github").first()
            )()

        if not integration:
            logger.error(f"No GitHub integration found for team {inputs.team_id}")
            return {
                "success": False,
                "error": "No GitHub integration configured for this team",
                "repo_path": None,
                "branch_name": None,
            }

        github_integration = GitHubIntegration(integration)

        # Check if token needs refresh
        if github_integration.access_token_expired():
            await database_sync_to_async(github_integration.refresh_access_token)()

        # Get the specific repository configured for this issue
        repository_config = task.repository_config
        if (
            not repository_config
            or not repository_config.get("organization")
            or not repository_config.get("repository")
        ):
            return {
                "success": False,
                "error": "No repository configured for this task. Please configure a repository in the task settings.",
                "repo_path": None,
                "branch_name": None,
            }

        org = repository_config["organization"]
        repository = repository_config["repository"]

        # Construct repository URL
        repo_url = f"https://github.com/{org}/{repository}"

        # Get access token
        access_token = integration.access_token

        # Generate branch name based on issue
        branch_name = f"task-{task.id}-{task.title.lower().replace(' ', '-').replace('_', '-')[:50]}"

        logger.info(f"Generated branch name: {branch_name}")

        # Create temporary directory for cloning
        temp_dir = tempfile.mkdtemp(prefix=f"issue-{inputs.task_id}-")
        repo_path = Path(temp_dir) / "repo"

        logger.info(f"Cloning repository {repo_url} to {repo_path}")

        # Prepare clone URL with authentication
        clone_url = repo_url
        if access_token:
            # Use x-access-token format for GitHub App tokens
            clone_url = clone_url.replace("https://github.com/", f"https://x-access-token:{access_token}@github.com/")

        # Get default branch for the repository
        default_branch = await database_sync_to_async(github_integration.get_default_branch)(repository)

        # Clone the repository with non-interactive settings
        clone_result = await _run_git_command(
            [
                "git",
                "clone",
                "--depth",
                "1",  # Shallow clone for faster download
                "--branch",
                default_branch,
                "--quiet",  # Reduce output
                clone_url,
                str(repo_path),
            ],
            env={"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"},
        )

        if not clone_result["success"]:
            logger.error(f"Failed to clone repository: {clone_result['error']}")
            return {
                "success": False,
                "error": f"Failed to clone repository: {clone_result['error']}",
                "repo_path": None,
                "branch_name": None,
            }

        logger.info("Repository cloned successfully")

        # Check if branch already exists remotely using the integration
        branch_info = await database_sync_to_async(github_integration.get_branch_info)(repository, branch_name)
        branch_exists_remotely = branch_info.get("success") and branch_info.get("exists")

        if branch_exists_remotely:
            logger.info(f"Branch {branch_name} already exists remotely, checking out existing branch")
            # Fetch the existing branch and checkout
            fetch_result = await _run_git_command(["git", "fetch", "origin", branch_name], cwd=repo_path)

            if not fetch_result["success"]:
                logger.error(f"Failed to fetch existing branch: {fetch_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to fetch existing branch: {fetch_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": None,
                }

            # Checkout the existing branch
            checkout_result = await _run_git_command(
                ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"], cwd=repo_path
            )

            if not checkout_result["success"]:
                logger.error(f"Failed to checkout existing branch: {checkout_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to checkout existing branch: {checkout_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": None,
                }

            logger.info(f"Checked out existing branch: {branch_name}")
        else:
            # Create and checkout new branch locally
            branch_result = await _run_git_command(["git", "checkout", "-b", branch_name], cwd=repo_path)

            if not branch_result["success"]:
                logger.error(f"Failed to create branch: {branch_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to create branch: {branch_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": None,
                }

            logger.info(f"Created and checked out new branch: {branch_name}")

            # Create an initial commit to have something to push
            commit_result = await _create_initial_commit(repo_path, task.title, str(task.id))

            if not commit_result["success"]:
                logger.error(f"Failed to create initial commit: {commit_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to create initial commit: {commit_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": branch_name,
                }

            # Push the new branch to GitHub
            push_result = await _run_git_command(["git", "push", "-u", "origin", branch_name], cwd=repo_path)

            if not push_result["success"]:
                logger.error(f"Failed to push branch to GitHub: {push_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to push branch to GitHub: {push_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": branch_name,
                }

            logger.info(f"Successfully pushed new branch {branch_name} to GitHub")

        # Update issue with branch name
        await database_sync_to_async(Task.objects.filter(id=inputs.task_id).update)(github_branch=branch_name)

        logger.info(f"Successfully cloned repo and prepared branch {branch_name} for issue {inputs.task_id}")

        return {
            "success": True,
            "repo_path": str(repo_path),
            "branch_name": branch_name,
            "repository": repository,
            "repo_url": repo_url,
            "default_branch": default_branch,
            "branch_exists_remotely": branch_exists_remotely,
            "access_token": access_token,  # Include access token for subsequent operations
        }

    except Exception as e:
        logger.exception(f"Error in clone_repo_and_create_branch_activity: {str(e)}")
        raise


@temporalio.activity.defn
async def cleanup_repo_activity(repo_path: str) -> bool:
    """Clean up the cloned repository directory."""

    bind_contextvars(repo_path=repo_path, activity="cleanup_repo")

    logger.info(f"Cleaning up repository at {repo_path}")

    try:
        if os.path.exists(repo_path):
            # Try to remove normally first
            try:
                shutil.rmtree(repo_path)
                logger.info(f"Successfully cleaned up repository at {repo_path}")
                return True
            except (OSError, FileNotFoundError) as e:
                # If normal removal fails (e.g., due to gc.pid or other locked files),
                # try a more robust approach
                logger.warning(f"Normal cleanup failed ({str(e)}), trying robust cleanup")

                # Try to forcefully remove with error handling
                def handle_remove_error(func, path, exc_info):
                    """Error handler for rmtree that handles permission and lock issues."""
                    import stat

                    try:
                        # Try to change permissions and retry
                        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                        func(path)
                    except:
                        # If we still can't remove it, just log and continue
                        logger.warning(f"Could not remove {path}, skipping")

                shutil.rmtree(repo_path, onerror=handle_remove_error)
                logger.info(f"Successfully cleaned up repository at {repo_path} (with error handling)")
                return True
        else:
            logger.warning(f"Repository path {repo_path} does not exist")
            return True
    except Exception as e:
        logger.exception(f"Failed to cleanup repository at {repo_path}: {str(e)}")
        # Don't fail the workflow just because cleanup failed
        logger.warning("Cleanup failed but continuing workflow")
        return True  # Return True to not fail the workflow


async def _create_initial_commit(repo_path: Path, task_title: str, task_id: str) -> dict[str, Any]:
    """Create a simple initial commit to enable pushing the branch."""
    try:
        logger.info(f"Creating initial commit for task {task_id}")

        # Configure git user (required for commits)
        await _run_git_command(["git", "config", "user.name", "PostHog Issue Tracker"], cwd=repo_path)

        await _run_git_command(["git", "config", "user.email", "noreply@posthog.com"], cwd=repo_path)

        # Create empty commit
        commit_result = await _run_git_command(
            ["git", "commit", "--allow-empty", "-m", f"Initial commit for task: {task_title}"], cwd=repo_path
        )

        if not commit_result["success"]:
            return {"success": False, "error": f"Failed to create commit: {commit_result['error']}"}

        logger.info(f"Successfully created initial commit for task {task_id}")
        return {"success": True}

    except Exception as e:
        error_msg = f"Failed to create initial commit: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "error": error_msg}


async def _run_git_command(
    command: list[str], cwd: Optional[Path] = None, env: Optional[dict] = None
) -> dict[str, Any]:
    """
    Run a git command asynchronously and return the result.

    Args:
        command: List of command arguments
        cwd: Working directory for the command
        env: Environment variables for the command

    Returns:
        Dict with success, stdout, stderr, and error fields
    """
    try:
        logger.info(f"Running command: {' '.join(command)} in {cwd or 'current directory'}")

        # Merge provided env with current environment
        process_env = dict(os.environ) if env else None
        if env and process_env:
            process_env.update(env)

        process = await asyncio.create_subprocess_exec(
            *command, cwd=cwd, env=process_env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        success = process.returncode == 0
        stdout_str = stdout.decode("utf-8").strip()
        stderr_str = stderr.decode("utf-8").strip()

        if success:
            logger.info(f"Command succeeded: {stdout_str}")
        else:
            logger.error(f"Command failed with return code {process.returncode}: {stderr_str}")

        return {
            "success": success,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "error": stderr_str if not success else None,
            "return_code": process.returncode,
        }

    except Exception as e:
        error_msg = f"Failed to execute command {' '.join(command)}: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "stdout": "", "stderr": "", "error": error_msg, "return_code": -1}
