"""
GitHub integration activities for issue tracker workflows.
"""

import os
import shutil
import asyncio
import tempfile
from pathlib import Path
from typing import Any

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger

from .inputs import CreatePRInputs, TaskProcessingInputs

logger = get_logger(__name__)


async def get_github_integration_for_task(task_id: str, team_id: int) -> tuple[Any, Any, str]:
    """
    Helper function to get GitHub integration, task, and repository for a task.

    Returns:
        Tuple of (task, github_integration, repository)

    Raises:
        Exception if no integration or repository is found
    """
    from django.apps import apps

    from posthog.models.integration import GitHubIntegration, Integration

    Task = apps.get_model("tasks", "Task")

    # Get the task
    task = await database_sync_to_async(Task.objects.select_related("team", "github_integration").get)(
        id=task_id, team_id=team_id
    )

    # Get the specific GitHub integration configured for this task
    if task.github_integration:
        integration = task.github_integration
    else:
        # Fallback to team's first GitHub integration
        integration = await database_sync_to_async(
            lambda: Integration.objects.filter(team_id=team_id, kind="github").first()
        )()

    if not integration:
        raise Exception("No GitHub integration found for this team")

    github_integration = GitHubIntegration(integration)

    # Check if token needs refresh
    if github_integration.access_token_expired():
        await database_sync_to_async(github_integration.refresh_access_token)()

    # Get the specific repository configured for this task
    repository_config = task.repository_config
    if not repository_config or not repository_config.get("organization") or not repository_config.get("repository"):
        raise Exception("No repository configured for this task. Please configure a repository in the task settings.")

    organization = repository_config["organization"]
    repository_name = repository_config["repository"]
    repository = f"{organization}/{repository_name}"

    return task, github_integration, repository


def _repo_basename(repository: str) -> str:
    """Return just the repository name (without organization) for GitHub API helpers.

    GitHubIntegration methods expect the repository name only, as they derive the
    organization from the installation/integration configuration. If a string of the
    form "org/repo" is provided, we strip the org part here.
    """
    if "/" in repository:
        return repository.split("/")[-1]
    return repository


@activity.defn
async def create_branch_activity(inputs: TaskProcessingInputs) -> dict[str, Any]:
    """
    Create a branch.

    Returns:
        Dict with branch creation results
    """
    bind_contextvars(task_id=inputs.task_id, team_id=inputs.team_id, activity="create_branch_activity")

    logger.info(f"Creating branch for issue {inputs.task_id}")

    try:
        task, github_integration, repository = await get_github_integration_for_task(inputs.task_id, inputs.team_id)
        repo_name = _repo_basename(repository)

        # Generate branch name based on issue
        branch_name = f"task-{task.id}-{task.title.lower().replace(' ', '-').replace('_', '-')[:20]}"

        # Check if branch already exists
        branch_info = await database_sync_to_async(github_integration.get_branch_info)(repo_name, branch_name)

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
        result = await database_sync_to_async(github_integration.create_branch)(repo_name, branch_name)

        if result.get("success"):
            logger.info(f"Successfully created branch {branch_name}")

            return {
                "success": True,
                "branch_name": branch_name,
                "repository": repo_name,
                "branch_exists": False,
                "sha": result.get("sha"),
                "ref": result.get("ref"),
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to create branch")}

    except Exception as e:
        logger.exception(f"Error creating branch: {str(e)}")
        return {"success": False, "error": f"Failed to create branch: {str(e)}"}


@activity.defn
async def create_pr_activity(inputs: CreatePRInputs) -> dict[str, Any]:
    """
    Create a pull request.

    Args:
        inputs: CreatePRInputs containing issue processing inputs and branch name

    Returns:
        Dict with PR creation results
    """
    issue_inputs = inputs.task_processing_inputs
    branch_name = inputs.branch_name

    bind_contextvars(task_id=issue_inputs.task_id, team_id=issue_inputs.team_id, activity="create_pr_activity")

    logger.info(f"Creating PR for issue {issue_inputs.task_id}")

    try:
        task, github_integration, repository = await get_github_integration_for_task(
            issue_inputs.task_id, issue_inputs.team_id
        )
        repo_name = _repo_basename(repository)

        # Get task details safely in async context
        def get_task_details():
            # Ensure related objects are fetched
            current_stage = task.current_stage
            stage_key = current_stage.key if current_stage else "backlog"
            priority = getattr(task, "priority", "N/A")
            return {
                "title": task.title,
                "id": str(task.id),
                "stage_key": stage_key,
                "priority": priority,
                "description": task.description or "No description provided",
            }

        task_details = await database_sync_to_async(get_task_details)()

        # Create PR title and body
        pr_title = f"Fix task: {task_details['title']}"
        pr_body = f"""
## Task: {task_details['title']}

**Task ID:** {task_details['id']}
**Status:** {task_details['stage_key']}
**Priority:** {task_details['priority']}

### Description
{task_details['description']}

---
*This PR was automatically created by PostHog Task Agent*
        """.strip()

        # Create the pull request
        logger.info(f"Creating PR with title: {pr_title}")
        logger.info(f"Head branch: {branch_name}, Repository: {repository}")

        result = await database_sync_to_async(github_integration.create_pull_request)(
            repository=repo_name, title=pr_title, body=pr_body, head_branch=branch_name
        )

        logger.info(f"GitHub PR creation result: {result}")

        if result.get("success"):
            logger.info(f"Successfully created PR #{result['pr_number']}")

            return {
                "success": True,
                "pr_number": result.get("pr_number"),
                "pr_url": result.get("pr_url"),
                "pr_id": result.get("pr_id"),
                "state": result.get("state"),
            }
        else:
            error_msg = result.get("error", "Failed to create pull request")
            logger.error(f"Failed to create PR: {error_msg}")
            return {"success": False, "error": error_msg, "message": error_msg}

    except Exception as e:
        logger.exception(f"Error creating PR: {str(e)}")
        return {"success": False, "error": f"Failed to create PR: {str(e)}"}


@activity.defn
async def clone_repo_and_create_branch_activity(inputs: TaskProcessingInputs) -> dict[str, Any]:
    """
    Clone the GitHub repository and create a new branch for the issue.

    Args:
        inputs: Issue processing inputs

    Returns:
        Dict with repo_path, branch_name, and status information
    """
    bind_contextvars(task_id=inputs.task_id, team_id=inputs.team_id, activity="clone_repo_and_create_branch")

    logger.info(f"Starting GitHub repo clone and branch creation for issue {inputs.task_id}")

    try:
        task, github_integration, repository_full = await get_github_integration_for_task(
            inputs.task_id, inputs.team_id
        )

        # Extract org and repository from full repository name
        org, repository = repository_full.split("/")

        # Get access token from integration
        integration = github_integration.integration

        # Construct repository URL
        repo_url = f"https://github.com/{org}/{repository}"

        # Get access token
        access_token = integration.access_token

        # Generate branch name based on issue
        branch_name = f"task-{task.id}-{task.title.lower().replace(' ', '-').replace('_', '-')[:20]}"

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

        # Check if branch already exists remotely
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

        logger.info(f"Successfully cloned repo and prepared branch {branch_name} for issue {inputs.task_id}")

        return {
            "success": True,
            "repo_path": str(repo_path),
            "branch_name": branch_name,
            "repository": repository,
            "repo_url": repo_url,
            "default_branch": default_branch,
            "branch_exists_remotely": branch_exists_remotely,
            "access_token": integration.access_token,  # Include access token for subsequent operations
        }

    except Exception as e:
        logger.exception(f"Error in clone_repo_and_create_branch_activity: {str(e)}")
        raise


@activity.defn
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


async def _run_git_command(command: list[str], cwd: Path | None = None, env: dict | None = None) -> dict[str, Any]:
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


@activity.defn
async def commit_local_changes_activity(args: dict) -> dict[str, Any]:
    """
    Scan local repository changes and commit them.

    This activity bridges local file changes (from Claude SDK) with the centralized GitHub integration.
    It scans the local repo for changes and commits them via GitHub API.
    """
    inputs = args["inputs"]
    repo_path = args["repo_path"]
    branch_name = args["branch_name"]
    task_title = args["task_title"]
    task_id = inputs["task_id"] if isinstance(inputs, dict) else inputs.task_id
    team_id = inputs["team_id"] if isinstance(inputs, dict) else inputs.team_id

    bind_contextvars(
        task_id=task_id,
        team_id=team_id,
        repo_path=repo_path,
        branch_name=branch_name,
        activity="commit_local_changes_activity",
    )

    logger.info(f"Scanning local changes and committing via GitHub integration for task {task_id}")

    try:
        # Import additional modules needed for file operations
        import os
        from pathlib import Path

        task, github_integration, repository = await get_github_integration_for_task(task_id, team_id)

        # Scan for changed files in the local repository
        original_cwd = os.getcwd()
        logger.info(f"Original working directory: {original_cwd}")
        logger.info(f"Changing to repo path: {repo_path}")

        try:
            os.chdir(repo_path)
            logger.info(f"Current working directory: {os.getcwd()}")
            # Make sure we're on the expected branch
            await _run_git_command(["git", "checkout", branch_name])

            # First, add all changed files to git index to ensure they're tracked
            add_result = await _run_git_command(["git", "add", "."])
            if not add_result["success"]:
                logger.warning(f"Failed to git add: {add_result['error']}")
            else:
                logger.info("Successfully added all changes to git index")

            # Get list of changed files using minimal git CLI
            result = await _run_git_command(["git", "status", "--porcelain"])
            if not result["success"]:
                return {"success": False, "error": f"Failed to check git status: {result['error']}"}

            git_output = result["stdout"].strip()
            logger.info(f"Git status output: '{git_output}'")

            # Also check for untracked files separately
            untracked_result = await _run_git_command(["git", "ls-files", "--others", "--exclude-standard"])
            if untracked_result["success"] and untracked_result["stdout"].strip():
                logger.info(f"Untracked files found: {untracked_result['stdout'].strip()}")

            if not git_output:
                logger.info("No working tree changes detected. Checking for unpushed local commits…")

                # Ensure we have up-to-date refs from origin
                await _run_git_command(["git", "fetch", "origin"])

                # Compare local HEAD to origin/branch without relying on rev-list tri-dot
                head_ok = await _run_git_command(["git", "rev-parse", "--verify", "HEAD"])
                remote_ok = await _run_git_command(["git", "rev-parse", "--verify", f"origin/{branch_name}"])

                if head_ok["success"] and remote_ok["success"]:
                    ahead_log = await _run_git_command(["git", "log", "--oneline", f"origin/{branch_name}..HEAD"])
                    if ahead_log["success"] and ahead_log["stdout"].strip():
                        logger.info("Local branch has commits ahead of origin. Pushing commits…")
                        push_res = await _run_git_command(
                            ["git", "push", "origin", f"HEAD:{branch_name}"],
                            env={"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"},
                        )
                        if push_res["success"]:
                            logger.info("Successfully pushed local commits to origin")
                            return {
                                "success": True,
                                "message": "Pushed existing local commits to origin",
                                "committed_files": [],
                            }
                        else:
                            logger.warning(f"Push failed: {push_res['error']}")
                    else:
                        logger.info("No local commits ahead of origin to push")
                else:
                    # If remote branch doesn't exist, create it
                    if not remote_ok["success"]:
                        logger.info("Remote branch doesn't exist yet. Creating upstream and pushing…")
                        push_new = await _run_git_command(
                            ["git", "push", "-u", "origin", branch_name],
                            env={"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"},
                        )
                        if push_new["success"]:
                            logger.info(f"Successfully pushed new branch {branch_name} to origin")
                            return {
                                "success": True,
                                "message": "Pushed new branch to origin",
                                "committed_files": [],
                            }
                        else:
                            logger.warning(f"Failed to push new branch: {push_new['error']}")

                # Nothing to do
                return {"success": True, "message": "No changes to commit", "committed_files": []}

            # Parse git status output to get changed files
            changed_files = []
            for line in git_output.split("\n"):
                if line.strip():
                    # Git status format: XY filename (where X and Y are status codes)
                    # Handle different git status formats properly
                    if len(line) >= 3:
                        status_codes = line[:2]
                        filename = line[3:].strip()

                        # Handle quoted filenames (git quotes filenames with spaces or special chars)
                        if filename.startswith('"') and filename.endswith('"'):
                            filename = filename[1:-1]  # Remove quotes

                        logger.info(f"Git status line: '{line}' -> status: '{status_codes}', filename: '{filename}'")

                        # Skip deleted files for now (GitHub API handles updates/creates)
                        if "D" not in status_codes:
                            changed_files.append(filename)
                            logger.info(f"Added file to commit list: {filename}")
                    else:
                        logger.warning(f"Unexpected git status line format: '{line}'")

            logger.info(f"Found {len(changed_files)} changed files: {changed_files}")

            committed_files = []

            # Read and commit each changed file via GitHub API
            for file_path in changed_files:
                try:
                    full_path = Path(repo_path) / file_path
                    logger.info(f"Processing file: {file_path}, full path: {full_path}")

                    if full_path.exists() and full_path.is_file():
                        # Read file content
                        with open(full_path, encoding="utf-8") as f:
                            content = f.read()

                        logger.info(f"Read file {file_path}, size: {len(content)} chars")

                        # Commit the file
                        commit_message = f"Update {file_path} for task #{task_id}: {task_title}"

                        logger.info(
                            f"Attempting to commit file: {file_path} to repository: {repository} on branch: {branch_name}"
                        )
                        logger.info(f"File size: {len(content)} characters")
                        logger.info(f"Commit message: {commit_message}")

                        result = await database_sync_to_async(github_integration.update_file)(
                            repository=_repo_basename(repository),
                            file_path=file_path,
                            content=content,
                            commit_message=commit_message,
                            branch=branch_name,
                        )

                        logger.info(f"GitHub API result for {file_path}: {result}")

                        if result.get("success"):
                            committed_files.append(
                                {
                                    "path": file_path,
                                    "commit_sha": result.get("commit_sha"),
                                    "file_sha": result.get("file_sha"),
                                    "html_url": result.get("html_url"),
                                }
                            )
                            logger.info(
                                f"Successfully committed file {file_path} with commit SHA: {result.get('commit_sha')}"
                            )
                        else:
                            error_msg = result.get("error", "Unknown error")
                            logger.error(f"Failed to commit file {file_path} to {repository}: {error_msg}")
                            logger.error(f"Full GitHub API result: {result}")

                            # Check if this is a 404 error (file/repo not found)
                            if "404" in str(error_msg) or "Not Found" in str(error_msg):
                                logger.warning(f"File or repository not found, skipping {file_path}")
                                continue  # Skip this file and continue with others
                            else:
                                # For other errors, fail the entire operation
                                return {
                                    "success": False,
                                    "error": f"Failed to commit file {file_path}: {error_msg}",
                                    "committed_files": committed_files,
                                }
                    else:
                        logger.warning(f"File {full_path} does not exist or is not a file, skipping")
                        continue

                except Exception as e:
                    logger.exception(f"Error processing file {file_path}: {str(e)}")
                    continue

            return {
                "success": True,
                "committed_files": committed_files,
                "total_files": len(committed_files),
                "message": f"Successfully committed {len(committed_files)} files via GitHub API",
            }

        finally:
            os.chdir(original_cwd)

    except Exception as e:
        logger.exception(f"Error committing local changes: {str(e)}")
        return {"success": False, "error": f"Failed to commit local changes: {str(e)}"}


async def get_github_integration_token(team_id: int, task_id: str) -> str:
    """Get GitHub access token from PostHog's GitHub integration."""
    try:
        from django.apps import apps

        from posthog.models.integration import GitHubIntegration, Integration

        Task = apps.get_model("tasks", "Task")

        # Get the task to access the specific GitHub integration
        task = await database_sync_to_async(Task.objects.select_related("github_integration").get)(
            id=task_id, team_id=team_id
        )

        # Get the specific GitHub integration configured for this task
        if task.github_integration:
            integration = task.github_integration
        else:
            # Fallback to team's first GitHub integration
            integration = await database_sync_to_async(
                lambda: Integration.objects.filter(team_id=team_id, kind="github").first()
            )()

        if not integration:
            logger.warning(f"No GitHub integration found for team {team_id}")
            return ""

        github_integration = GitHubIntegration(integration)

        # Check if token needs refresh
        if github_integration.access_token_expired():
            await database_sync_to_async(github_integration.refresh_access_token)()

        return github_integration.integration.access_token or ""

    except Exception as e:
        logger.exception(f"Error getting GitHub integration token for team {team_id}, task {task_id}: {str(e)}")
        return ""


@activity.defn
async def create_pr_and_update_task_activity(args: dict) -> dict[str, Any]:
    """Create a PR after agent work is completed and update the task with PR URL."""
    try:
        # Extract parameters from args
        task_id = args["task_id"]
        team_id = args["team_id"]
        branch_name = args["branch_name"]

        logger.info(f"Creating PR and updating task {task_id} with branch {branch_name}")

        # Create PR using existing create_pr_activity
        from .inputs import CreatePRInputs, TaskProcessingInputs

        task_processing_inputs = TaskProcessingInputs(task_id=task_id, team_id=team_id)
        pr_inputs = CreatePRInputs(task_processing_inputs=task_processing_inputs, branch_name=branch_name)

        pr_result = await create_pr_activity(pr_inputs)

        if pr_result.get("success") and pr_result.get("pr_url"):
            # Update task with PR URL and branch name
            from django.apps import apps

            Task = apps.get_model("tasks", "Task")

            def update_task_pr_info():
                task = Task.objects.get(id=task_id, team_id=team_id)
                task.github_pr_url = pr_result["pr_url"]
                task.github_branch = branch_name
                task.save(update_fields=["github_pr_url", "github_branch"])
                logger.info(f"Updated task {task_id} with PR URL: {pr_result['pr_url']} and branch: {branch_name}")
                return task

            await database_sync_to_async(update_task_pr_info)()

            return {
                "success": True,
                "pr_url": pr_result["pr_url"],
                "pr_number": pr_result.get("pr_number"),
                "pr_id": pr_result.get("pr_id"),
                "branch_name": branch_name,
                "message": f"PR created successfully: {pr_result['pr_url']}",
            }
        else:
            error = pr_result.get("error", "Unknown error creating PR")
            logger.error(f"Failed to create PR for task {task_id}: {error}")
            return {"success": False, "error": f"Failed to create PR: {error}"}

    except Exception as e:
        logger.exception(f"Failed to create PR and update task {task_id}: {e}")
        return {"success": False, "error": str(e)}
