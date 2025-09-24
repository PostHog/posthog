#!/usr/bin/env python3
"""
Simple test to verify MCP server is loading tools correctly.
"""

import asyncio
import logging

from sandbox_mcp import SandboxMCPManager

logging.basicConfig(level=logging.INFO)


async def test_mcp_server_tools():
    """Test that MCP server loads tools correctly"""
    print("🧪 Testing MCP Server Tool Loading")

    try:
        async with SandboxMCPManager() as mcp_manager:
            server = mcp_manager.get_server()

            print(f"✅ MCP server created: {type(server)}")

            # Try to inspect the server object
            if hasattr(server, '_tools'):
                print(f"🔧 Server has _tools attribute: {server._tools}")
            if hasattr(server, 'tools'):
                print(f"🔧 Server has tools attribute: {server.tools}")
            if hasattr(server, '__dict__'):
                print(f"🔧 Server attributes: {list(server.__dict__.keys())}")

            # Try to get available tools through different methods
            if hasattr(server, 'list_tools'):
                try:
                    tools = await server.list_tools()
                    print(f"🔧 Available tools via list_tools(): {tools}")
                except Exception as e:
                    print(f"❌ Error calling list_tools(): {e}")

            print("✅ MCP server inspection complete")

    except Exception as e:
        print(f"❌ Error testing MCP server: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_mcp_server_tools())