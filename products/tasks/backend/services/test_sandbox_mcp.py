#!/usr/bin/env python3
"""
Test example showing how to use the sandbox MCP server with Claude Code SDK.
"""

import os
import asyncio
import tempfile
from pathlib import Path

from claude_code_sdk import ClaudeCodeOptions, create_sdk_mcp_server, query, tool
from sandbox_mcp import SandboxMCPManager


async def test_sandbox_mcp_server():
    """Test the sandbox MCP server with Claude Code SDK"""

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ Please set ANTHROPIC_API_KEY")
        return

    print("🧪 Testing Sandbox MCP Server")

    try:
        # Use the sandbox MCP manager
        async with SandboxMCPManager() as mcp_manager:
            server = mcp_manager.get_server()
            sandbox = mcp_manager.sandbox

            @tool("print", "Print a message to the console", {"message": "str"})
            def print_message(message: str):
                """Print a message to the console"""
                print(f"🔧 PRINT TOOL CALLED! Message: {message}")
                print(message)

            @tool("bash", "Execute a bash command", {"command": "str"})
            async def bash_command(command: str):
                """Execute a bash command"""
                print(f"🔧 BASH TOOL CALLED! Command: {command}")
                result = await sandbox.execute(command)
                print(f"🔧 BASH RESULT: {result}")
                return result

            tools_server = create_sdk_mcp_server(
                name="tools_server",
                version="1.0.0",
                tools=[print_message, bash_command],
            )

            # Configure Claude Code to use sandbox tools instead of built-in ones
            print(f"🔧 MCP server created: {server}")
            print(f"🔧 Available tools on server: {getattr(server, 'tools', 'unknown')}")

            options = ClaudeCodeOptions(
                max_turns=5,
                cwd=Path(tempfile.mkdtemp()),
                permission_mode="acceptEdits",
                mcp_servers={"sandbox": server, "tools": tools_server},
                allowed_tools=[
                    "mcp__tools__print",
                    "mcp__tools__bash",
                ],
            )

            # Test: List available MCP servers and tools
            print(f"\n🔍 Checking MCP servers and tools...")

            prompt = """Please use the sandbox MCP tools to perform these tasks:

0. Use the print tool to print "Hello from sandbox this works!"
1. Use the bash tool to run 'whoami' command

Make sure to use the MCP tools, not the built-in tools."""

            print(f"\n🚀 Sending prompt to Claude...")
            print(f"📝 Prompt: {prompt}")

            turn = 0
            async for message in query(prompt=prompt, options=options):
                turn += 1
                print(f"\n--- Turn {turn} ---")

                if hasattr(message, "__class__"):
                    message_type = message.__class__.__name__
                    print(f"📨 Message type: {message_type}")

                    if message_type == "AssistantMessage":
                        for content in message.content:
                            if hasattr(content, "text"):
                                text = content.text
                                print(f"📝 Assistant: {text[:20000]}...")
                            elif hasattr(content, "name"):
                                tool_name = content.name
                                tool_input = getattr(content, "input", {})
                                print(f"🔧 Tool: {tool_name}")
                                print(f"   Input: {tool_input}")

                    elif message_type == "UserMessage":
                        print("👤 Tool result received")
                        if isinstance(message.content, list):
                            for content in message.content:
                                if hasattr(content, "content"):
                                    result = str(content.content)
                                    print(f"   📤 Result: {result[:10500]}...")

                    elif message_type == "SystemMessage":
                        print(f"🔧 System: {message.subtype}")

                    elif message_type == "ResultMessage":
                        print("✅ Query completed!")
                        print(f"   Duration: {message.duration_ms}ms")
                        print(f"   Turns: {message.num_turns}")
                        break

                if turn > 20:  # Safety limit
                    break

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_sandbox_mcp_server())
