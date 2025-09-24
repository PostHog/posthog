"""
Sandbox Bash tool - executes bash commands in a remote sandbox environment.
"""

import logging
from typing import Any

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

logger = logging.getLogger(__name__)


async def bash_tool(args: dict[str, Any], sandbox: SandboxEnvironment) -> dict[str, Any]:
    """Execute bash command in sandbox"""
    logger.info(f"🔧 SANDBOX BASH TOOL CALLED! Command: {args.get('command', '')}")

    command = args.get("command", "")
    timeout = args.get("timeout", 60)

    try:
        result = await sandbox.execute(command, timeout_seconds=timeout)

        # Format output similar to built-in Bash tool
        output = result.stdout
        if result.stderr:
            output += f"\nstderr: {result.stderr}"

        return {
            "content": [{
                "type": "text",
                "text": output
            }],
            "isError": result.exit_code != 0
        }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Sandbox execution error: {str(e)}"
            }],
            "isError": True
        }