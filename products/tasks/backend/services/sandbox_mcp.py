"""
MCP server wrapper that creates sandbox versions of Claude Code tools.
"""

from typing import Optional

from claude_code_sdk import create_sdk_mcp_server, tool

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment, SandboxEnvironmentConfig
from products.tasks.backend.services.tools.bash import bash_tool
from products.tasks.backend.services.tools.edit import edit_tool
from products.tasks.backend.services.tools.glob import glob_tool
from products.tasks.backend.services.tools.grep import grep_tool
from products.tasks.backend.services.tools.read import read_tool
from products.tasks.backend.services.tools.write import write_tool


def create_sandbox_mcp_server(sandbox: SandboxEnvironment):
    """
    Create an MCP server with sandbox tools.

    Args:
        sandbox: The sandbox environment to use for tool execution

    Returns:
        An MCP server that can be used with Claude Code SDK
    """

    # Wrap each tool function with @tool decorator and sandbox context
    @tool(
        "bash",
        "Execute a bash command in the sandbox environment",
        {"command": "str", "description": "str", "timeout": "int"},
    )
    async def wrapped_bash_tool(args):
        return await bash_tool(args, sandbox)

    @tool("read", "Read a file from the sandbox", {"file_path": "str", "offset": "int", "limit": "int"})
    async def wrapped_read_tool(args):
        return await read_tool(args, sandbox)

    @tool("write", "Write content to a file in the sandbox", {"file_path": "str", "content": "str"})
    async def wrapped_write_tool(args):
        return await write_tool(args, sandbox)

    @tool(
        "edit",
        "Edit a file in the sandbox by replacing text",
        {"file_path": "str", "old_string": "str", "new_string": "str", "replace_all": "bool"},
    )
    async def wrapped_edit_tool(args):
        return await edit_tool(args, sandbox)

    @tool(
        "grep",
        "Search for patterns in files in the sandbox",
        {"pattern": "str", "path": "str", "case_insensitive": "bool", "files_only": "bool"},
    )
    async def wrapped_grep_tool(args):
        return await grep_tool(args, sandbox)

    @tool("glob", "Find files matching a pattern in the sandbox", {"pattern": "str", "path": "str"})
    async def wrapped_glob_tool(args):
        return await glob_tool(args, sandbox)

    # Create and return the MCP server
    return create_sdk_mcp_server(
        name="sandbox",
        version="1.0.0",
        tools=[
            wrapped_bash_tool,
            wrapped_read_tool,
            wrapped_write_tool,
            wrapped_edit_tool,
            wrapped_grep_tool,
            wrapped_glob_tool,
        ],
    )


class SandboxMCPManager:
    """
    Manager for sandbox MCP server lifecycle.
    Handles sandbox creation/destruction and MCP server setup.
    """

    def __init__(self, config: Optional[SandboxEnvironmentConfig] = None):
        self.config = config
        self.sandbox: Optional[SandboxEnvironment] = None
        self.server = None

    async def __aenter__(self):
        """Create sandbox and MCP server"""
        if self.config:
            self.sandbox = await SandboxEnvironment.create(self.config)
        else:
            # Use default config if none provided
            from products.tasks.backend.services.sandbox_environment import SandboxEnvironmentTemplate

            default_config = SandboxEnvironmentConfig(
                name="mcp-sandbox",
                template=SandboxEnvironmentTemplate.UBUNTU_LATEST_X86_64,
                default_execution_timeout_seconds=60,
            )
            self.sandbox = await SandboxEnvironment.create(default_config)

        self.server = create_sandbox_mcp_server(self.sandbox)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up sandbox"""
        if self.sandbox:
            await self.sandbox.destroy()
            self.sandbox = None
        self.server = None

    def get_server(self):
        """Get the MCP server instance"""
        return self.server
