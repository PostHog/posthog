"""PostHog Agent Toolkit for LangChain using MCP."""

from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient


class PostHogAgentToolkit:
    """
    A toolkit for interacting with PostHog tools via the MCP server.
    """

    _tools: list[BaseTool] | None
    client: MultiServerMCPClient

    def __init__(
        self,
        url: str = "https://mcp.posthog.com/mcp",
        personal_api_key: str | None = None,
    ):
        """
        Initialize the PostHog Agent Toolkit.

        Args:
            url: The URL of the PostHog MCP server (default: https://mcp.posthog.com/mcp/)
            personal_api_key: PostHog API key for authentication
        """

        if not personal_api_key:
            raise ValueError("A personal API key is required.")

        config = self._get_config(url, personal_api_key)

        self.client = MultiServerMCPClient(config)

        self._tools: list[BaseTool] | None = None

    @staticmethod
    def _get_config(url: str, personal_api_key: str) -> dict[str, dict[str, Any]]:
        return {
            "posthog": {
                "url": url,
                "transport": "streamable_http",
                "headers": {
                    "Authorization": f"Bearer {personal_api_key}",
                    "X-Client-Package": "posthog-agent-toolkit",
                },
            }
        }

    async def get_tools(self) -> list[BaseTool]:
        """
        Get all available PostHog tools as LangChain compatible tools.

        Returns:
            List of BaseTool instances that can be used with LangChain agents
        """
        if self._tools is None:
            self._tools = await self.client.get_tools()
        return self._tools
