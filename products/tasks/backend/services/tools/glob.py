"""
Sandbox Glob tool - finds files matching patterns in a remote sandbox environment.
"""

import logging
from typing import Any

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

logger = logging.getLogger(__name__)


async def glob_tool(args: dict[str, Any], sandbox: SandboxEnvironment) -> dict[str, Any]:
    """Find files matching pattern in sandbox"""
    logger.info(f"🔍 SANDBOX GLOB TOOL CALLED! Pattern: {args.get('pattern', '')}")
    pattern = args.get("pattern", "")
    path = args.get("path", ".")

    try:
        # Convert ** to find syntax
        if "**" in pattern:
            pattern = pattern.replace("**", "*")

        command = f"find '{path}' -type f -name '{pattern}' 2>/dev/null | sort"
        result = await sandbox.execute(command)

        if result.exit_code == 0:
            files = result.stdout.strip()
            if files:
                return {
                    "content": [{
                        "type": "text",
                        "text": files
                    }]
                }
            else:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No files found"
                    }]
                }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"File search failed: {result.stderr}"
                }],
                "isError": True
            }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Sandbox glob error: {str(e)}"
            }],
            "isError": True
        }