"""
Sandbox Edit tool - edits files in a remote sandbox environment by replacing text.
"""

import logging
from typing import Any

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

logger = logging.getLogger(__name__)


async def edit_tool(args: dict[str, Any], sandbox: SandboxEnvironment) -> dict[str, Any]:
    """Edit file in sandbox by replacing text"""
    logger.info(f"✏️ SANDBOX EDIT TOOL CALLED! File: {args.get('file_path', '')}")
    file_path = args.get("file_path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    replace_all = args.get("replace_all", False)

    try:
        # Read the file
        read_result = await sandbox.execute(f"cat '{file_path}'")
        if read_result.exit_code != 0:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Failed to read {file_path}: {read_result.stderr}"
                }],
                "isError": True
            }

        content = read_result.stdout

        # Apply replacement
        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1 if old_string in content else 0

        if count == 0:
            return {
                "content": [{
                    "type": "text",
                    "text": f"String not found in file: {old_string}"
                }],
                "isError": True
            }

        # Write back the modified content
        escaped_content = new_content.replace("'", "'\"'\"'")
        write_command = f"cat > '{file_path}' << 'EOF'\n{escaped_content}\nEOF"
        write_result = await sandbox.execute(write_command)

        if write_result.exit_code == 0:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Successfully replaced {count} occurrence(s) in {file_path}"
                }]
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Failed to write changes: {write_result.stderr}"
                }],
                "isError": True
            }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Sandbox edit error: {str(e)}"
            }],
            "isError": True
        }