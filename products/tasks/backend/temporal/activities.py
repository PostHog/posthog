import os
import typing

import temporalio
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger

from .github_activities import get_github_integration_token

logger = get_logger(__name__)


@activity.defn
async def ai_agent_work_activity(args: dict) -> dict[str, typing.Any]:
    """Execute AI agent work using Claude Code SDK with local file access and GitHub MCP integration."""
    inputs = args["inputs"]
    repo_path = args["repo_path"]  # Local cloned repository path
    repository = args["repository"]  # GitHub repository name (e.g., "posthog/posthog")
    branch_name = args["branch_name"]

    # Handle serialized inputs - Temporal converts objects to dicts
    if isinstance(inputs, dict):
        task_id = inputs["task_id"]
        team_id = inputs["team_id"]
    else:
        task_id = inputs.task_id
        team_id = inputs.team_id

    bind_contextvars(
        task_id=task_id,
        team_id=team_id,
        repo_path=repo_path,
        repository=repository,
        branch_name=branch_name,
    )

    logger.info(
        f"Starting AI agent work for task {task_id} in local repo {repo_path} (GitHub: {repository}) on branch {branch_name}"
    )

    try:
        from django.apps import apps

        Task = apps.get_model("tasks", "Task")

        # Get the task details
        logger.info(f"Fetching task details for {task_id}")
        task = await database_sync_to_async(Task.objects.get)(id=task_id, team_id=team_id)
        logger.info(f"Task details: title='{task.title}', origin='{task.origin_product}'")

        # Create progress tracking record
        def create_progress():
            from django.apps import apps

            TaskProgress = apps.get_model("tasks", "TaskProgress")
            return TaskProgress.objects.create(
                task=task,
                team_id=team_id,
                status=TaskProgress.Status.STARTED,
                current_step="Initializing Claude Code execution",
                total_steps=0,  # Unknown duration - don't show misleading progress bar
                workflow_id=getattr(temporalio.activity.info(), "workflow_id", ""),
                workflow_run_id=getattr(temporalio.activity.info(), "workflow_run_id", ""),
                activity_id=getattr(temporalio.activity.info(), "activity_id", ""),
            )

        progress = await database_sync_to_async(create_progress)()

        # Prepare the prompt for Claude Code SDK
        prompt = f"""
  <context>
    Repository: {repository}
    Branch: {branch_name}
    You have access to the local repository files for fast read/write operations.
    You also have access to GitHub via the GitHub MCP server for additional repository operations.
    Work with local files for your main implementation, and use GitHub MCP for any additional repository queries.
    Commit changes to the repository regularly.
  </context>

  <role>
    PostHog AI Coding Agent — autonomously transform a ticket into a merge-ready pull request that follows existing project conventions.
  </role>

  <tools>
    Local file system (for main implementation work)
    PostHog MCP server (for PostHog operations)
  </tools>

  <constraints>
    - Follow existing style and patterns you discover in the repo.
    - Try not to add new external dependencies, only if needed.
    - Implement structured logging and error handling; never log secrets.
    - Avoid destructive shell commands.
    - ALWAYS create appropriate .gitignore files to exclude build artifacts, dependencies, and temporary files.
  </constraints>

  <checklist>
    - Created or updated .gitignore file with appropriate exclusions
    - Created dependency files (requirements.txt, package.json, etc.) with exact versions
    - Added clear setup/installation instructions to README.md
    - Code compiles and tests pass.
    - Added or updated tests.
    - Captured meaningful events with PostHog SDK.
    - Wrapped new logic in an PostHog feature flag.
    - Updated docs, readme or type hints if needed.
    - Verified no build artifacts or dependencies are being committed
  </checklist>

  <ticket>
    <title>{task.title}</title>
    <description>{task.description}</description>
  </ticket>

  <task>
    Complete the ticket in a thoughtful step by step manner. Plan thoroughly and make sure to add logging and error handling as well as cover edge cases.
  </task>

  <workflow>
  - first make a plan and create a todo list
  - execute the todo list one by one
  - test the changes
  </workflow>

  <output_format>
    Once finished respond with a summary of changes made
  </output_format>

  <thinking>
    Use this area as a private scratch-pad for step-by-step reasoning; erase before final output.
  </thinking>
"""

        logger.info(f"Prepared prompt for Claude Code SDK (length: {len(prompt)} chars)")

        # Get GitHub integration token for MCP authentication
        github_token = await get_github_integration_token(team_id, task_id)
        if not github_token:
            logger.warning(f"No GitHub token available for task {task_id}, Claude SDK will have limited GitHub access")

        # Use Claude Code SDK to execute the work
        logger.info("Calling Claude Code SDK...")
        result = await _execute_claude_code_sdk(prompt, repo_path, repository, branch_name, github_token, progress)

        # Mark progress as completed
        def mark_completed():
            progress.mark_completed()

        await database_sync_to_async(mark_completed)()

        logger.info(f"AI agent work completed for task {task_id} with result length: {len(result)}")
        return {
            "success": True,
            "result": result,
            "task_id": task_id,
            "branch_name": branch_name,
            "progress_id": str(progress.id),
        }

    except Exception as e:
        logger.exception(f"Error in AI agent work for task {task_id}: {str(e)}")
        error_str = str(e)

        # Mark progress as failed if it exists
        try:
            if "progress" in locals():

                def mark_failed():
                    progress.mark_failed(error_str)

                await database_sync_to_async(mark_failed)()
        except Exception:
            pass  # Don't fail the main exception handling

        return {"success": False, "error": str(e), "task_id": task_id, "branch_name": branch_name}


async def _parse_claude_message_for_progress(message, turn_number: int) -> str | None:
    """Parse Claude Code SDK messages to extract meaningful progress information."""
    try:
        # Get the message type - it's usually the class name
        message_type = type(message).__name__

        # Handle different message types based on their actual structure
        if message_type == "SystemMessage":
            # Skip system init messages as they're not interesting
            if hasattr(message, "subtype") and message.subtype == "init":
                return f"🔧 Claude SDK initialized"
            return None

        elif message_type == "AssistantMessage":
            # Parse assistant messages for tool use and text content
            if hasattr(message, "content") and message.content:
                for content_block in message.content:
                    content_type = type(content_block).__name__

                    if content_type == "ToolUseBlock":
                        # Extract tool information
                        tool_name = getattr(content_block, "name", "unknown")
                        tool_input = getattr(content_block, "input", {})

                        # Map tool names to emojis and descriptions
                        tool_icons = {
                            "Task": "📋",
                            "Read": "📖",
                            "Write": "✍️",
                            "Edit": "✏️",
                            "MultiEdit": "✏️",
                            "Bash": "⚡",
                            "Glob": "🔍",
                            "Grep": "🔎",
                            "LS": "📁",
                            "WebFetch": "🌐",
                            "WebSearch": "🔍",
                            "TodoWrite": "📋",
                            "NotebookRead": "📓",
                            "NotebookEdit": "📓",
                        }

                        # Handle MCP tools
                        if tool_name.startswith("mcp__posthog"):
                            icon = "📊"
                            tool_display = "PostHog API"
                        elif tool_name.startswith("mcp__github"):
                            icon = "🐙"
                            tool_display = "GitHub API"
                        else:
                            icon = tool_icons.get(tool_name, "🔧")
                            tool_display = tool_name

                        # Extract parameters for more context
                        params = ""
                        if tool_input:
                            if tool_name in ["Read", "Write", "Edit", "MultiEdit"]:
                                file_path = tool_input.get("file_path", "")
                                if file_path:
                                    # Show just the filename
                                    filename = file_path.split("/")[-1]
                                    params = f" {filename}"
                            elif tool_name == "Bash":
                                command = tool_input.get("command", "")
                                if command:
                                    params = f" `{command[:40]}{'...' if len(command) > 40 else ''}`"
                            elif tool_name in ["Glob", "Grep"]:
                                pattern = tool_input.get("pattern", "")
                                if pattern:
                                    params = f" '{pattern}'"
                            elif tool_name == "TodoWrite":
                                todos = tool_input.get("todos", [])
                                if todos:
                                    params = f" ({len(todos)} items)"

                        return f"{icon} {tool_display}{params}"

                    elif content_type == "TextBlock":
                        # Extract meaningful text content
                        text = getattr(content_block, "text", "")
                        if text:
                            text_lower = text.lower()
                            # Look for high-level progress indicators
                            if any(
                                phrase in text_lower for phrase in ["starting", "let me start", "beginning", "first"]
                            ):
                                return f"🚀 {text[:80]}{'...' if len(text) > 80 else ''}"
                            elif any(phrase in text_lower for phrase in ["completed", "finished", "done successfully"]):
                                return f"✅ {text[:80]}{'...' if len(text) > 80 else ''}"
                            elif any(phrase in text_lower for phrase in ["creating", "implementing", "adding"]):
                                return f"🔨 {text[:80]}{'...' if len(text) > 80 else ''}"
                            elif any(phrase in text_lower for phrase in ["testing", "running tests", "checking"]):
                                return f"🧪 {text[:80]}{'...' if len(text) > 80 else ''}"
                            elif any(phrase in text_lower for phrase in ["error", "failed", "problem"]):
                                return f"⚠️ {text[:80]}{'...' if len(text) > 80 else ''}"
                            elif any(phrase in text_lower for phrase in ["looking", "searching", "finding"]):
                                return f"🔍 {text[:80]}{'...' if len(text) > 80 else ''}"
            return None

        elif message_type == "UserMessage":
            # Parse tool results from user messages
            if hasattr(message, "content") and message.content:
                for content_item in message.content:
                    if isinstance(content_item, dict) and content_item.get("type") == "tool_result":
                        tool_content = content_item.get("content", "")

                        # Try to extract meaningful information from tool results
                        if isinstance(tool_content, str):
                            content_lower = tool_content.lower()

                            # Handle successful operations
                            if "successfully" in content_lower:
                                if "file" in content_lower and any(
                                    word in content_lower for word in ["updated", "created", "written"]
                                ):
                                    return f"✅ File operation completed"
                                elif "todo" in content_lower:
                                    return f"✅ Todo list updated"
                                else:
                                    return f"✅ Operation successful"

                            # Handle file edit results
                            elif "lines" in content_lower and ("added" in content_lower or "updated" in content_lower):
                                import re

                                lines_match = re.search(r"(\d+)\s*lines?\s*(added|updated|changed)", tool_content)
                                if lines_match:
                                    count = lines_match.group(1)
                                    action = lines_match.group(2)
                                    return f"📝 {action.title()} {count} lines"

                            # Handle command results
                            elif "exit status" in content_lower or "exit code" in content_lower:
                                if "exit status 0" in content_lower or "exit code 0" in content_lower:
                                    return f"⚡ Command succeeded"
                                else:
                                    return f"❌ Command failed"

                            # Handle search results
                            elif tool_content.count("\n") > 5:  # Multiple results
                                lines = tool_content.strip().split("\n")
                                return f"🔍 Found {len(lines)} results"
            return None

        return None  # No meaningful progress info extracted

    except Exception as e:
        logger.debug(f"Error parsing message for progress: {e}")
        return None


async def _execute_claude_code_sdk(
    prompt: str, repo_path: str, repository: str, branch_name: str, github_token: str, progress=None
) -> str:
    """Execute Claude Code SDK using Python SDK with local file access and GitHub MCP integration."""
    logger.info(f"Executing Claude Code SDK in local repo {repo_path} (GitHub: {repository}) on branch {branch_name}")

    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set, cannot use Claude Code SDK")
        raise Exception("ANTHROPIC_API_KEY environment variable is required for Claude Code SDK")

    try:
        # Try to use the Python SDK first (more reliable)
        try:
            from pathlib import Path

            from claude_code_sdk import ClaudeCodeOptions, query

            logger.info("Using Claude Code Python SDK")

            if progress:

                def update_step():
                    progress.update_progress("Starting Claude Code SDK execution", 0)
                    progress.append_output("🚀 Starting Claude Code SDK execution...")

                await database_sync_to_async(update_step)()

            # Debug: Check the repository state before Claude runs
            logger.info(f"Repository path for Claude Code SDK: {repo_path}")
            logger.info(f"Repository path exists: {os.path.exists(repo_path)}")
            if os.path.exists(repo_path):
                # List files in the repository
                try:
                    files = os.listdir(repo_path)
                    logger.info(f"Files in repository before Claude runs: {files[:10]}...")  # Show first 10 files

                    # Check git status before Claude runs
                    original_cwd = os.getcwd()
                    os.chdir(repo_path)
                    import subprocess

                    git_status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
                    logger.info(f"Git status before Claude runs: '{git_status.stdout.strip()}'")
                    os.chdir(original_cwd)
                except Exception as e:
                    logger.warning(f"Failed to list repository contents: {e}")

            options = ClaudeCodeOptions(
                max_turns=100,
                cwd=Path(repo_path),  # Local repository access
                permission_mode="acceptEdits",  # Auto-accept file edits
                allowed_tools=[
                    "Read",
                    "Write",
                    "Edit",
                    "Bash",
                    "Glob",
                    "Grep",
                    "WebFetch",
                    "WebSearch",
                    "mcp__posthog",
                    "mcp__github",
                ],  # Allow all necessary tools
                mcp_tools=["mcp__posthog", "mcp__github"],
                mcp_servers={
                    "posthog": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "mcp-remote@latest",
                            "https://mcp.posthog.com/sse",
                            "--header",
                            "Authorization:${POSTHOG_AUTH_HEADER}",
                        ],
                        "env": {"POSTHOG_AUTH_HEADER": f"Bearer {os.environ.get('POSTHOG_PERSONAL_API_KEY', '')}"},
                    },
                    "github": {
                        "command": "npx",
                        "args": ["-y", "@github/github-mcp-server"],
                        "env": {
                            "GITHUB_PERSONAL_ACCESS_TOKEN": github_token,
                        },
                    },
                },
            )

            result_text = ""
            message_count = 0
            async for message in query(prompt=prompt, options=options):
                message_count += 1

                # Log the actual message structure for debugging
                logger.info(f"Received message {message_count}: type={getattr(message, 'type', 'unknown')}")
                if hasattr(message, "__dict__"):
                    logger.debug(f"Message attributes: {list(message.__dict__.keys())}")

                # Parse and display meaningful progress information
                if progress:
                    progress_msg = await _parse_claude_message_for_progress(message, message_count)
                    if progress_msg:

                        def append_progress(msg=progress_msg, count=message_count):
                            progress.append_output(msg)
                            progress.update_progress(f"Turn {count}", 0)

                        await database_sync_to_async(append_progress)()

                # Try different ways to extract content
                if hasattr(message, "type"):
                    if message.type == "assistant":
                        # Try multiple ways to get content
                        text_content = ""
                        if hasattr(message, "message") and hasattr(message.message, "content"):
                            for content_block in message.message.content:
                                if hasattr(content_block, "text"):
                                    text_content += content_block.text
                        elif hasattr(message, "content"):
                            text_content = str(message.content)
                        elif hasattr(message, "text"):
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
                        error_msg = getattr(message, "error", "Unknown error")
                        logger.error(f"SDK error: {error_msg}")
                        if progress:

                            def error_update(err=error_msg):
                                progress.append_output(f"❌ Error: {err}")

                            await database_sync_to_async(error_update)()
                        break

                # Also try to extract content from unknown message types
                else:
                    # Log the raw message for debugging but don't spam progress
                    logger.debug(f"Unknown message type, raw message: {str(message)[:200]}")
                    if progress:

                        def append_unknown(count=message_count):
                            progress.append_output(f"💭 Claude processing (turn {count})")

                        await database_sync_to_async(append_unknown)()

            logger.info(
                f"Claude Code Python SDK execution completed, result length: {len(result_text)}, messages: {message_count}"
            )

            # Debug: Check the repository state after Claude runs
            if os.path.exists(repo_path):
                try:
                    original_cwd = os.getcwd()
                    os.chdir(repo_path)

                    # Check git status after Claude runs
                    git_status_after = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
                    logger.info(f"Git status after Claude runs: '{git_status_after.stdout.strip()}'")

                    # Check for any new or modified files
                    git_diff = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
                    logger.info(f"Git diff --name-only after Claude: '{git_diff.stdout.strip()}'")

                    # Check untracked files
                    git_untracked = subprocess.run(
                        ["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True
                    )
                    logger.info(f"Untracked files after Claude: '{git_untracked.stdout.strip()}'")

                    os.chdir(original_cwd)
                except Exception as e:
                    logger.warning(f"Failed to check repository state after Claude: {e}")

            return result_text or "Claude Code execution completed successfully"

        except ImportError as e:
            logger.exception(f"Claude Code Python SDK not available: {e}")
            raise Exception(f"Claude Code SDK is required but not installed: {e}")

    except Exception as e:
        logger.exception(f"Error executing Claude Code SDK: {str(e)}")
        raise
