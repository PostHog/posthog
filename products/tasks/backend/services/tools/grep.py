"""
Sandbox Grep tool - searches for patterns in files in a remote sandbox environment.
"""

import logging
from typing import Any

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

logger = logging.getLogger(__name__)


async def grep_tool(args: dict[str, Any], sandbox: SandboxEnvironment) -> dict[str, Any]:
    """Search patterns in sandbox files"""
    logger.info(f"🔍 SANDBOX GREP TOOL CALLED! Pattern: {args.get('pattern', '')}")
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    case_insensitive = args.get("case_insensitive", False)
    files_only = args.get("files_only", False)

    try:
        flags = []
        if case_insensitive:
            flags.append("-i")
        if files_only:
            flags.append("-l")
        else:
            flags.append("-n")  # Include line numbers

        flags_str = " ".join(flags)
        command = f"grep -r {flags_str} '{pattern}' '{path}' 2>/dev/null | head -1000"

        result = await sandbox.execute(command)

        if result.exit_code in [0, 1]:  # 0 = matches found, 1 = no matches
            matches = result.stdout.strip()
            if matches:
                return {
                    "content": [{
                        "type": "text",
                        "text": matches
                    }]
                }
            else:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No matches found"
                    }]
                }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Search failed: {result.stderr}"
                }],
                "isError": True
            }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Sandbox grep error: {str(e)}"
            }],
            "isError": True
        }