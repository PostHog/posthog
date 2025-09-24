"""
Sandbox Write tool - writes files to a remote sandbox environment.
"""

import logging
from typing import Any

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

logger = logging.getLogger(__name__)


async def write_tool(args: dict[str, Any], sandbox: SandboxEnvironment) -> dict[str, Any]:
    """Write file to sandbox"""
    logger.info(f"✍️ SANDBOX WRITE TOOL CALLED! File: {args.get('file_path', '')}")
    file_path = args.get("file_path", "")
    content = args.get("content", "")

    try:
        # Create parent directory if needed
        dir_command = f"mkdir -p $(dirname '{file_path}')"
        await sandbox.execute(dir_command)

        # Write content using heredoc to handle special characters
        escaped_content = content.replace("'", "'\"'\"'")
        write_command = f"cat > '{file_path}' << 'EOF'\n{escaped_content}\nEOF"

        result = await sandbox.execute(write_command)

        if result.exit_code == 0:
            # Verify file was written
            verify_result = await sandbox.execute(f"wc -l '{file_path}'")
            lines = 0
            if verify_result.exit_code == 0 and verify_result.stdout:
                try:
                    lines = int(verify_result.stdout.split()[0])
                except:
                    pass

            return {
                "content": [{
                    "type": "text",
                    "text": f"Successfully wrote {lines} lines to {file_path}"
                }]
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Failed to write {file_path}: {result.stderr}"
                }],
                "isError": True
            }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Sandbox write error: {str(e)}"
            }],
            "isError": True
        }