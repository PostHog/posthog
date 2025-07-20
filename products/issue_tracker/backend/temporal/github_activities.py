import asyncio
import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Any

import temporalio

from posthog.temporal.common.logger import bind_contextvars, get_logger
from posthog.sync import database_sync_to_async
from .inputs import IssueProcessingInputs
from .github_client import GitHubClient

logger = get_logger(__name__)


@temporalio.activity.defn
async def clone_repo_and_create_branch_activity(inputs: IssueProcessingInputs) -> dict[str, Any]:
    """
    Clone the GitHub repository and create a new branch for the issue.
    
    Returns:
        Dict with repo_path, branch_name, and status information
    """
    bind_contextvars(
        issue_id=inputs.issue_id,
        team_id=inputs.team_id,
        activity="clone_repo_and_create_branch"
    )

    logger.info(f"Starting GitHub repo clone and branch creation for issue {inputs.issue_id}")

    try:
        # Import models inside activity to avoid Django apps loading issues
        from django.apps import apps
        Issue = apps.get_model("issue_tracker", "Issue")
        GitHubIntegration = apps.get_model("issue_tracker", "GitHubIntegration")

        # Get the issue and GitHub integration
        issue = await database_sync_to_async(Issue.objects.select_related('team').get)(
            id=inputs.issue_id,
            team_id=inputs.team_id
        )

        try:
            github_integration = await database_sync_to_async(
                lambda: issue.team.github_integration
            )()
        except Exception:
            logger.error(f"No GitHub integration found for team {inputs.team_id}")
            return {
                "success": False,
                "error": "No GitHub integration configured for this team",
                "repo_path": None,
                "branch_name": None
            }

        if not github_integration.is_active:
            logger.warning(f"GitHub integration is disabled for team {inputs.team_id}")
            return {
                "success": False,
                "error": "GitHub integration is disabled",
                "repo_path": None,
                "branch_name": None
            }

        # Generate branch name
        branch_name = github_integration.get_branch_name(issue.title, str(issue.id))
        logger.info(f"Generated branch name: {branch_name}")

        # Create temporary directory for cloning
        temp_dir = tempfile.mkdtemp(prefix=f"issue-{inputs.issue_id}-")
        repo_path = Path(temp_dir) / "repo"

        logger.info(f"Cloning repository {github_integration.repo_url} to {repo_path}")

        # Prepare git commands
        clone_url = github_integration.repo_url
        if github_integration.github_token:
            # Add token to URL for authentication
            if clone_url.startswith("https://github.com/"):
                clone_url = clone_url.replace(
                    "https://github.com/",
                    f"https://{github_integration.github_token}@github.com/"
                )

        # Clone the repository
        clone_result = await _run_git_command([
            "git", "clone",
            "--depth", "1",  # Shallow clone for faster download
            "--branch", github_integration.default_branch,
            clone_url,
            str(repo_path)
        ])

        if not clone_result["success"]:
            logger.error(f"Failed to clone repository: {clone_result['error']}")
            return {
                "success": False,
                "error": f"Failed to clone repository: {clone_result['error']}",
                "repo_path": None,
                "branch_name": None
            }

        logger.info("Repository cloned successfully")

        # Check if branch already exists remotely
        remote_branches_result = await _run_git_command([
            "git", "ls-remote", "--heads", "origin", branch_name
        ], cwd=repo_path)

        branch_exists_remotely = (
            remote_branches_result["success"] and
            remote_branches_result["stdout"].strip()
        )

        if branch_exists_remotely:
            logger.info(f"Branch {branch_name} already exists remotely, checking out existing branch")
            # Fetch the existing branch and checkout
            fetch_result = await _run_git_command([
                "git", "fetch", "origin", branch_name
            ], cwd=repo_path)

            if not fetch_result["success"]:
                logger.error(f"Failed to fetch existing branch: {fetch_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to fetch existing branch: {fetch_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": None
                }

            # Checkout the existing branch
            checkout_result = await _run_git_command([
                "git", "checkout", "-b", branch_name, f"origin/{branch_name}"
            ], cwd=repo_path)

            if not checkout_result["success"]:
                logger.error(f"Failed to checkout existing branch: {checkout_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to checkout existing branch: {checkout_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": None
                }

            logger.info(f"Checked out existing branch: {branch_name}")
        else:
            # Create and checkout new branch
            branch_result = await _run_git_command([
                "git", "checkout", "-b", branch_name
            ], cwd=repo_path)

            if not branch_result["success"]:
                logger.error(f"Failed to create branch: {branch_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to create branch: {branch_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": None
                }

            logger.info(f"Created and checked out new branch: {branch_name}")

            # Create an initial commit to have something to push
            commit_result = await _create_initial_commit(
                repo_path,
                issue.title,
                str(issue.id),
                github_integration.github_token
            )

            if not commit_result["success"]:
                logger.error(f"Failed to create initial commit: {commit_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to create initial commit: {commit_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": branch_name
                }

            # Push the new branch to GitHub
            push_result = await _run_git_command([
                "git", "push", "-u", "origin", branch_name
            ], cwd=repo_path)

            if not push_result["success"]:
                logger.error(f"Failed to push branch to GitHub: {push_result['error']}")
                return {
                    "success": False,
                    "error": f"Failed to push branch to GitHub: {push_result['error']}",
                    "repo_path": str(repo_path),
                    "branch_name": branch_name
                }

            logger.info(f"Successfully pushed new branch {branch_name} to GitHub")

        # Update issue with branch name
        await database_sync_to_async(Issue.objects.filter(id=inputs.issue_id).update)(
            github_branch=branch_name
        )

        logger.info(f"Successfully cloned repo and prepared branch {branch_name} for issue {inputs.issue_id}")

        return {
            "success": True,
            "repo_path": str(repo_path),
            "branch_name": branch_name,
            "repo_url": github_integration.repo_url,
            "default_branch": github_integration.default_branch,
            "branch_exists_remotely": branch_exists_remotely
        }

    except Exception as e:
        logger.error(f"Error in clone_repo_and_create_branch_activity: {str(e)}")
        raise


@temporalio.activity.defn
async def cleanup_repo_activity(repo_path: str) -> bool:
    """Clean up the cloned repository directory."""

    bind_contextvars(
        repo_path=repo_path,
        activity="cleanup_repo"
    )

    logger.info(f"Cleaning up repository at {repo_path}")

    try:
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
            logger.info(f"Successfully cleaned up repository at {repo_path}")
            return True
        else:
            logger.warning(f"Repository path {repo_path} does not exist")
            return True
    except Exception as e:
        logger.error(f"Failed to cleanup repository at {repo_path}: {str(e)}")
        return False


@temporalio.activity.defn
async def validate_github_integration_activity(inputs: IssueProcessingInputs) -> dict[str, Any]:
    """
    Validate GitHub integration and repository access.
    
    Returns:
        Dict with validation results and repository information
    """
    bind_contextvars(
        issue_id=inputs.issue_id,
        team_id=inputs.team_id,
        activity="validate_github_integration"
    )

    logger.info(f"Validating GitHub integration for team {inputs.team_id}")

    try:
        # Import models inside activity
        from django.apps import apps
        Issue = apps.get_model("issue_tracker", "Issue")

        # Get the issue and GitHub integration
        issue = await database_sync_to_async(Issue.objects.select_related('team').get)(
            id=inputs.issue_id,
            team_id=inputs.team_id
        )

        try:
            github_integration = await database_sync_to_async(
                lambda: issue.team.github_integration
            )()
        except Exception:
            return {
                "success": False,
                "error": "No GitHub integration configured for this team"
            }

        if not github_integration.is_active:
            return {
                "success": False,
                "error": "GitHub integration is disabled"
            }

        if not github_integration.github_token:
            return {
                "success": False,
                "error": "No GitHub token configured"
            }

        # Create GitHub client and validate access
        client = GitHubClient(
            token=github_integration.github_token,
            repo_owner=github_integration.repo_owner,
            repo_name=github_integration.repo_name
        )

        # Check repository access
        repo_info = await client.get_repository_info()
        if not repo_info["success"]:
            return {
                "success": False,
                "error": f"Cannot access repository: {repo_info['error']}"
            }

        logger.info(f"GitHub integration validated successfully for {github_integration.repo_full_name}")

        return {
            "success": True,
            "repo_info": repo_info,
            "integration": {
                "repo_owner": github_integration.repo_owner,
                "repo_name": github_integration.repo_name,
                "repo_url": github_integration.repo_url,
                "default_branch": github_integration.default_branch,
                "branch_prefix": github_integration.branch_prefix
            }
        }

    except Exception as e:
        logger.error(f"Error validating GitHub integration: {str(e)}")
        return {
            "success": False,
            "error": f"Validation failed: {str(e)}"
        }


async def _create_initial_commit(
    repo_path: Path,
    issue_title: str,
    issue_id: str,
    github_token: str
) -> dict[str, Any]:
    """Create a simple initial commit to enable pushing the branch."""
    try:
        logger.info(f"Creating initial commit for issue {issue_id}")

        # Configure git user (required for commits)
        await _run_git_command([
            "git", "config", "user.name", "PostHog Issue Tracker"
        ], cwd=repo_path)

        await _run_git_command([
            "git", "config", "user.email", "noreply@posthog.com"
        ], cwd=repo_path)

        # Create empty commit
        commit_result = await _run_git_command([
            "git", "commit", "--allow-empty", "-m", f"Initial commit for issue: {issue_title}"
        ], cwd=repo_path)

        if not commit_result["success"]:
            return {
                "success": False,
                "error": f"Failed to create commit: {commit_result['error']}"
            }

        logger.info(f"Successfully created initial commit for issue {issue_id}")
        return {"success": True}

    except Exception as e:
        error_msg = f"Failed to create initial commit: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}


async def _run_git_command(command: list[str], cwd: Optional[Path] = None) -> dict[str, Any]:
    """
    Run a git command asynchronously and return the result.
    
    Args:
        command: List of command arguments
        cwd: Working directory for the command
        
    Returns:
        Dict with success, stdout, stderr, and error fields
    """
    try:
        logger.info(f"Running command: {' '.join(command)} in {cwd or 'current directory'}")

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        success = process.returncode == 0
        stdout_str = stdout.decode('utf-8').strip()
        stderr_str = stderr.decode('utf-8').strip()

        if success:
            logger.info(f"Command succeeded: {stdout_str}")
        else:
            logger.error(f"Command failed with return code {process.returncode}: {stderr_str}")

        return {
            "success": success,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "error": stderr_str if not success else None,
            "return_code": process.returncode
        }

    except Exception as e:
        error_msg = f"Failed to execute command {' '.join(command)}: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": error_msg,
            "return_code": -1
        }
