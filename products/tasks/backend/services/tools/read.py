"""
Sandbox Read tool - reads files from a remote sandbox environment.
"""

import logging
from typing import Any

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

logger = logging.getLogger(__name__)


async def read_tool(args: dict[str, Any], sandbox: SandboxEnvironment) -> dict[str, Any]:
    """Read file from sandbox"""
    logger.info(f"📖 SANDBOX READ TOOL CALLED! File: {args.get('file_path', '')}")
    file_path = args.get("file_path", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", 2000)

    try:
        if offset > 0:
            command = f"tail -n +{offset + 1} '{file_path}' | head -n {limit} | cat -n"
        else:
            command = f"head -n {limit} '{file_path}' | cat -n"

        result = await sandbox.execute(command)

        if result.exit_code == 0:
            return {
                "content": [{
                    "type": "text",
                    "text": result.stdout
                }]
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error reading {file_path}: {result.stderr}"
                }],
                "isError": True
            }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Sandbox read error: {str(e)}"
            }],
            "isError": True
        }