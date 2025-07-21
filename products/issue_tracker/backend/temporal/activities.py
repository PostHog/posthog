import temporalio
import os
import subprocess
from typing import Any

from posthog.temporal.common.logger import bind_contextvars, get_logger
from posthog.sync import database_sync_to_async
from .inputs import IssueProcessingInputs

logger = get_logger(__name__)


@temporalio.activity.defn
async def process_issue_moved_to_todo_activity(inputs: IssueProcessingInputs) -> str:
    """
    Background processing activity when an issue is moved to TODO status.
    This is where you can add any background work you want to happen when
    a card moves to the todo column. Examples:
    - Send notifications
    - Update external systems
    - Generate reports
    - Process dependencies
    - Log analytics events
    """
    bind_contextvars(
        issue_id=inputs.issue_id,
        team_id=inputs.team_id,
        status_change=f"{inputs.previous_status} -> {inputs.new_status}",
    )

    logger.info(f"Starting background processing for issue {inputs.issue_id}")

    try:
        # Import Issue model inside the activity to avoid Django apps loading issues
        from django.apps import apps

        Issue = apps.get_model("issue_tracker", "Issue")

        # Get the issue from the database
        issue = await database_sync_to_async(Issue.objects.get)(id=inputs.issue_id, team_id=inputs.team_id)

        # Verify the issue is still in todo status
        if issue.status != "todo":
            logger.warning(f"Issue {inputs.issue_id} is no longer in todo status, skipping processing")
            return f"Issue status changed, skipping processing"

        # TODO: Add your actual background processing logic here
        # Examples:

        # 1. Send a notification
        logger.info(f"Issue '{issue.title}' moved to TODO - sending notifications...")

        # 2. Update external systems
        logger.info(f"Updating external tracking systems for issue {inputs.issue_id}...")

        # 3. Log analytics event
        logger.info(f"Logging analytics event for todo transition...")

        # 4. Process any automated tasks
        logger.info(f"Running automated processing for issue type: {issue.origin_product}")

        # For now, just log the successful processing
        logger.info(f"Successfully processed issue {inputs.issue_id} moved to TODO")

        return f"Successfully processed issue {inputs.issue_id} background tasks"

    except Exception as e:
        if "DoesNotExist" in str(type(e)):
            logger.exception(f"Issue {inputs.issue_id} not found in team {inputs.team_id}")
        else:
            logger.exception(f"Error processing issue {inputs.issue_id}: {str(e)}")
        raise


@temporalio.activity.defn
async def update_issue_status_activity(args: dict) -> str:
    """Update the status of an issue."""
    issue_id = args["issue_id"]
    team_id = args["team_id"]
    new_status = args["new_status"]

    bind_contextvars(
        issue_id=issue_id,
        team_id=team_id,
        new_status=new_status,
    )

    logger.info(f"Updating issue {issue_id} status to {new_status}")

    try:
        from django.apps import apps

        Issue = apps.get_model("issue_tracker", "Issue")

        # Update the issue status
        def update_status():
            issue = Issue.objects.get(id=issue_id, team_id=team_id)
            issue.status = new_status
            issue.save()
            return issue

        issue = await database_sync_to_async(update_status)()

        logger.info(f"Successfully updated issue {issue_id} status to {new_status}")
        return f"Issue {issue_id} status updated to {new_status}"

    except Exception as e:
        if "DoesNotExist" in str(type(e)):
            logger.exception(f"Issue {issue_id} not found in team {team_id}")
        else:
            logger.exception(f"Error updating issue {issue_id} status: {str(e)}")
        raise


@temporalio.activity.defn
async def get_issue_details_activity(args: dict) -> dict[str, Any]:
    """Get issue details from the database."""
    issue_id = args["issue_id"]
    team_id = args["team_id"]
    bind_contextvars(issue_id=issue_id, team_id=team_id)

    try:
        from django.apps import apps
        Issue = apps.get_model("issue_tracker", "Issue")

        issue = await database_sync_to_async(Issue.objects.get)(id=issue_id, team_id=team_id)

        return {
            "id": str(issue.id),
            "title": issue.title,
            "description": issue.description,
            "status": issue.status,
            "origin_product": issue.origin_product
        }

    except Exception as e:
        if "DoesNotExist" in str(type(e)):
            logger.exception(f"Issue {issue_id} not found in team {team_id}")
        else:
            logger.exception(f"Error getting issue {issue_id} details: {str(e)}")
        raise


@temporalio.activity.defn
async def ai_agent_work_activity(args: dict) -> dict[str, Any]:
    """Execute AI agent work using Claude Code SDK."""
    inputs = args["inputs"]
    repo_path = args["repo_path"]
    branch_name = args["branch_name"]

    # Handle serialized inputs - Temporal converts objects to dicts
    if isinstance(inputs, dict):
        issue_id = inputs["issue_id"]
        team_id = inputs["team_id"]
    else:
        issue_id = inputs.issue_id
        team_id = inputs.team_id

    bind_contextvars(
        issue_id=issue_id,
        team_id=team_id,
        repo_path=repo_path,
        branch_name=branch_name,
    )

    logger.info(f"Starting AI agent work for issue {issue_id} in repo {repo_path} on branch {branch_name}")

    try:
        from django.apps import apps
        Issue = apps.get_model("issue_tracker", "Issue")

        # Get the issue details
        logger.info(f"Fetching issue details for {issue_id}")
        issue = await database_sync_to_async(Issue.objects.get)(id=issue_id, team_id=team_id)
        logger.info(f"Issue details: title='{issue.title}', origin='{issue.origin_product}'")

        # Create progress tracking record
        def create_progress():
            from django.apps import apps
            IssueProgress = apps.get_model("issue_tracker", "IssueProgress")
            return IssueProgress.objects.create(
                issue=issue,
                team_id=team_id,
                status=IssueProgress.Status.STARTED,
                current_step="Initializing Claude Code execution",
                total_steps=0,  # Unknown duration - don't show misleading progress bar
                workflow_id=getattr(temporalio.activity.info(), 'workflow_id', ''),
                workflow_run_id=getattr(temporalio.activity.info(), 'workflow_run_id', ''),
                activity_id=getattr(temporalio.activity.info(), 'activity_id', '')
            )

        progress = await database_sync_to_async(create_progress)()

        # Prepare the prompt for Claude Code SDK
        prompt = f"""I need you to implement this feature request:

**Issue Title:** {issue.title}
**Description:** {issue.description}
**Product:** {issue.origin_product}

**Important guidelines:**
- Follow the existing code style and patterns you find in the codebase
- Use posthog in the set up, and use the posthog sdk to track events if its available
- Add appropriate error handling and logging
- Do not use any external libraries, only use the ones that are already installed in the codebase
- Do not run lint or build commands to test the implementation, just use the codebase as is
- Use Posthog MCP to add new feature flags, to put features behind

Please implement this feature step by step, explaining what you're doing as you go."""

        logger.info(f"Prepared prompt for Claude Code SDK (length: {len(prompt)} chars)")

        # Use Claude Code SDK to execute the work
        logger.info("Calling Claude Code SDK...")
        result = await _execute_claude_code_sdk(prompt, repo_path, progress)

        # Mark progress as completed
        def mark_completed():
            progress.mark_completed()
        await database_sync_to_async(mark_completed)()

        logger.info(f"AI agent work completed for issue {issue_id} with result length: {len(result)}")
        return {
            "success": True,
            "result": result,
            "issue_id": issue_id,
            "branch_name": branch_name,
            "progress_id": str(progress.id)
        }

    except Exception as e:
        logger.exception(f"Error in AI agent work for issue {issue_id}: {str(e)}")

        # Mark progress as failed if it exists
        try:
            if 'progress' in locals():
                def mark_failed():
                    progress.mark_failed(str(e))
                await database_sync_to_async(mark_failed)()
        except Exception:
            pass  # Don't fail the main exception handling

        return {
            "success": False,
            "error": str(e),
            "issue_id": issue_id,
            "branch_name": branch_name
        }


async def _execute_claude_code_sdk(prompt: str, repo_path: str, progress=None) -> str:
    """Execute Claude Code SDK using Python SDK."""
    logger.info(f"Executing Claude Code SDK in {repo_path}")

    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set, cannot use Claude Code SDK")
        raise Exception("ANTHROPIC_API_KEY environment variable is required for Claude Code SDK")

    try:
        # Try to use the Python SDK first (more reliable)
        try:
            import anyio
            from claude_code_sdk import query, ClaudeCodeOptions
            from pathlib import Path

            logger.info("Using Claude Code Python SDK")

            if progress:
                def update_step():
                    progress.update_progress("Starting Claude Code SDK execution", 0)
                    progress.append_output("🚀 Starting Claude Code SDK execution...")
                await database_sync_to_async(update_step)()

            logger.info(f"POSTHOG_PERSONAL_API_KEY: {os.environ.get('POSTHOG_PERSONAL_API_KEY', '')}")

            options = ClaudeCodeOptions(
                max_turns=30,
                cwd=Path(repo_path),
                permission_mode="acceptEdits",  # Auto-accept file edits
                allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch", "mcp__posthog"],  # Allow all necessary tools
                mcp_tools=["mcp__posthog"],
                mcp_servers={
                    "posthog": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "mcp-remote@latest",
                        "https://mcp.posthog.com/sse",
                        "--header",
                        "Authorization:${POSTHOG_AUTH_HEADER}"
                    ],
                    "env": {
                        "POSTHOG_AUTH_HEADER": f"Bearer {os.environ.get('POSTHOG_PERSONAL_API_KEY', '')}"
                    }
                    }
                }
            )

            result_text = ""
            message_count = 0
            async for message in query(prompt=prompt, options=options):
                message_count += 1

                # Log the actual message structure for debugging
                logger.info(f"Received message {message_count}: type={getattr(message, 'type', 'unknown')}")
                if hasattr(message, '__dict__'):
                    logger.debug(f"Message attributes: {list(message.__dict__.keys())}")

                # Stream all message content to progress for visibility
                if progress:
                    def append_message():
                        progress.append_output(f"📩 Message {message_count}: {str(message)[:1000]}...")
                        progress.update_progress(f"Processing message {message_count}", 0)
                    await database_sync_to_async(append_message)()

                # Try different ways to extract content
                if hasattr(message, 'type'):
                    if message.type == "assistant":
                        # Try multiple ways to get content
                        text_content = ""
                        if hasattr(message, 'message') and hasattr(message.message, 'content'):
                            for content_block in message.message.content:
                                if hasattr(content_block, 'text'):
                                    text_content += content_block.text
                        elif hasattr(message, 'content'):
                            text_content = str(message.content)
                        elif hasattr(message, 'text'):
                            text_content = message.text

                        if text_content:
                            result_text += text_content + "\n"
                            logger.info(f"Extracted text content: {text_content[:100]}...")

                    elif message.type == "result":
                        logger.info(f"SDK completed with result: {getattr(message, 'subtype', 'unknown')}")
                        if progress:
                            def final_update():
                                progress.append_output(f"✅ Claude Code execution completed")
                                progress.update_progress("Execution completed", 0)
                            await database_sync_to_async(final_update)()
                        break
                    elif message.type == "error":
                        error_msg = getattr(message, 'error', 'Unknown error')
                        logger.error(f"SDK error: {error_msg}")
                        if progress:
                            def error_update():
                                progress.append_output(f"❌ Error: {error_msg}")
                            await database_sync_to_async(error_update)()
                        break

                # Also try to extract content from unknown message types
                else:
                    # Log the raw message for debugging
                    logger.info(f"Unknown message type, raw message: {str(message)[:500]}")
                    if progress:
                        def append_raw():
                            progress.append_output(f"🔍 Raw message: {str(message)[:500]}...")
                        await database_sync_to_async(append_raw)()

            logger.info(f"Claude Code Python SDK execution completed, result length: {len(result_text)}, messages: {message_count}")
            return result_text or "Claude Code execution completed successfully"

        except ImportError as e:
            logger.error(f"Claude Code Python SDK not available: {e}")
            raise Exception(f"Claude Code SDK is required but not installed: {e}")

    except Exception as e:
        logger.error(f"Error executing Claude Code SDK: {str(e)}")
        raise




@temporalio.activity.defn
async def commit_and_push_changes_activity(args: dict) -> dict[str, Any]:
    """Commit and push changes to the repository."""
    repo_path = args["repo_path"]
    branch_name = args["branch_name"]
    issue_title = args["issue_title"]
    issue_id = args["issue_id"]

    bind_contextvars(
        repo_path=repo_path,
        branch_name=branch_name,
        issue_id=issue_id,
    )

    logger.info(f"Committing and pushing changes for issue {issue_id}")

    try:
        original_cwd = os.getcwd()
        os.chdir(repo_path)

        try:
            # Check if there are any changes to commit
            result = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True)
            if not result.stdout.strip():
                logger.info("No changes to commit")
                return {"success": True, "message": "No changes to commit"}

            # Add all changes
            subprocess.run(['git', 'add', '.'], check=True)

            # Commit changes
            commit_message = f"feat: {issue_title}\n\nImplemented solution for issue {issue_id}\n\n🤖 Generated with Claude Code SDK"
            subprocess.run(['git', 'commit', '-m', commit_message], check=True)

            # Push the branch (use force push to handle conflicts with existing branch)
            subprocess.run(['git', 'push', '--force', 'origin', branch_name], check=True)

            logger.info(f"Successfully committed and pushed changes for issue {issue_id}")
            return {
                "success": True,
                "message": f"Changes committed and pushed to branch {branch_name}",
                "branch_name": branch_name
            }

        finally:
            os.chdir(original_cwd)

    except subprocess.CalledProcessError as e:
        error_msg = f"Git operation failed: {e}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"Error committing and pushing changes: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}


@temporalio.activity.defn
async def create_pull_request_activity(args: dict) -> dict[str, Any]:
    """Create a pull request for the completed work."""
    repo_path = args["repo_path"]
    branch_name = args["branch_name"]
    issue_id = args["issue_id"]
    issue_title = args["issue_title"]
    issue_description = args["issue_description"]

    bind_contextvars(
        repo_path=repo_path,
        branch_name=branch_name,
        issue_id=issue_id,
    )

    logger.info(f"Creating pull request for issue {issue_id}")

    try:
        original_cwd = os.getcwd()
        os.chdir(repo_path)

        try:
            # Check if gh CLI is available
            gh_check = subprocess.run(['gh', '--version'], capture_output=True, text=True)
            if gh_check.returncode != 0:
                logger.warning("GitHub CLI (gh) not available, skipping PR creation")
                return {"success": True, "message": "GitHub CLI not available, PR creation skipped"}

            # Create pull request
            pr_title = f"feat: {issue_title}"
            pr_body = f"""## Summary
{issue_description}

## Changes Made
This pull request implements the solution for issue {issue_id}.

## Testing
Please review and test the changes before merging.

🤖 Generated with Claude Code SDK
Issue ID: {issue_id}
"""

            result = subprocess.run([
                'gh', 'pr', 'create',
                '--title', pr_title,
                '--body', pr_body,
                '--head', branch_name
            ], capture_output=True, text=True)

            if result.returncode == 0:
                pr_url = result.stdout.strip()
                logger.info(f"Pull request created successfully: {pr_url}")
                return {
                    "success": True,
                    "pr_url": pr_url,
                    "message": f"Pull request created: {pr_url}"
                }
            else:
                error_msg = f"Failed to create pull request: {result.stderr}"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}

        finally:
            os.chdir(original_cwd)

    except subprocess.CalledProcessError as e:
        error_msg = f"GitHub CLI operation failed: {e}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"Error creating pull request: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}


@temporalio.activity.defn
async def update_issue_github_info_activity(args: dict) -> str:
    """Update issue with GitHub branch and PR information."""
    issue_id = args["issue_id"]
    team_id = args["team_id"]
    branch_name = args["branch_name"]
    pr_url = args.get("pr_url")

    bind_contextvars(
        issue_id=issue_id,
        team_id=team_id,
        branch_name=branch_name,
        pr_url=pr_url,
    )

    logger.info(f"Updating issue {issue_id} with GitHub info")

    try:
        from django.apps import apps
        Issue = apps.get_model("issue_tracker", "Issue")

        def update_github_info():
            issue = Issue.objects.get(id=issue_id, team_id=team_id)
            issue.github_branch = branch_name
            if pr_url:
                issue.github_pr_url = pr_url
            issue.save()
            return issue

        issue = await database_sync_to_async(update_github_info)()

        logger.info(f"Successfully updated issue {issue_id} with GitHub info")
        return f"Issue {issue_id} updated with branch: {branch_name}" + (f", PR: {pr_url}" if pr_url else "")

    except Exception as e:
        if "DoesNotExist" in str(type(e)):
            logger.exception(f"Issue {issue_id} not found in team {team_id}")
        else:
            logger.exception(f"Error updating issue {issue_id} GitHub info: {str(e)}")
        raise
