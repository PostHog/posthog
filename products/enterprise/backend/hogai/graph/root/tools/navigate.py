from typing import Any, Self

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import AssistantNavigateUrl

from posthog.models import Team, User

from products.enterprise.backend.hogai.context.context import AssistantContextManager
from products.enterprise.backend.hogai.tool import MaxTool
from products.enterprise.backend.hogai.utils.prompt import format_prompt_string
from products.enterprise.backend.hogai.utils.types.base import AssistantState, NodePath

NAVIGATION_TOOL_PROMPT = """
Use the `navigate` tool to move between different pages in the PostHog application.
These pages are tied to PostHog's products and/or functionalities and provide tools for retrieving information or performing actions.
After navigating to a page, you can use the tools available there to retrieve information or perform actions.
Make sure that the state is aligned with the user's request using the tools available.

# When to use this tool
- To access tools that are only available on specific pages.
- To navigate to a page that the user is looking for.
- If the user asks to do something fun in the platform, you can navigate them to the `game368hedgehogs` page.

# When NOT to use this tool:
- If the currently defined tools can be used to assist the user. For example, if a SQL query fails, the tools of the SQL Editor page will not fix the query.

# List of pages and the tools available on a page
{{{scene_descriptions}}}
""".strip()


class NavigateToolArgs(BaseModel):
    page_key: AssistantNavigateUrl = Field(
        description="The specific key identifying the page to navigate to. Must be one of the predefined literal values."
    )


class NavigateTool(MaxTool):
    name: str = "navigate"
    description: str = NAVIGATION_TOOL_PROMPT
    context_prompt_template: str = (
        "You're currently on the {current_page} page. "
        "You can navigate around the PostHog app using the `navigate` tool."
    )
    args_schema: type[BaseModel] = NavigateToolArgs

    def _run_impl(self, page_key: AssistantNavigateUrl) -> tuple[str, Any]:
        # Note that page_key should get replaced by a nicer breadcrumbs-based name in the frontend
        # but it's useful for the LLM to still have the page_key in chat history
        return f"Navigated to **{page_key}**.", {"page_key": page_key}

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        if context_manager is None:
            context_manager = AssistantContextManager(team, user, config)
        tool_context = context_manager.get_contextual_tools().get("navigate", {})
        tool_description = format_prompt_string(NAVIGATION_TOOL_PROMPT, **tool_context)
        return cls(
            team=team,
            user=user,
            node_path=node_path,
            state=state,
            config=config,
            context_manager=context_manager,
            description=tool_description,
        )
