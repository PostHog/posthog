from typing import Literal, Self

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from posthog.models import Team, User

from products.enterprise.backend.hogai.context.context import AssistantContextManager
from products.enterprise.backend.hogai.graph.sql.mixins import HogQLDatabaseMixin
from products.enterprise.backend.hogai.tool import MaxTool
from products.enterprise.backend.hogai.utils.prompt import format_prompt_string
from products.enterprise.backend.hogai.utils.types.base import AssistantState, NodePath

from .read_billing_tool.tool import ReadBillingTool

READ_DATA_BILLING_PROMPT = """
# Billing information

Use this tool with the "billing_info" kind to retrieve the billing information if the user asks about their billing, subscription, product usage, spending, or cost reduction strategies.
You can use the information retrieved to check which PostHog products and add-ons the user has activated, how much they are spending, their usage history across all products in the last 30 days, as well as trials, spending limits, billing period, and more.
If the user wants to reduce their spending, always call this tool to get suggestions on how to do so.
If an insight shows zero data, it could mean either the query is looking at the wrong data or there was a temporary data collection issue. You can investigate potential dips in usage/captured data using the billing tool.
""".strip()

READ_DATA_PROMPT = f"""
Use this tool to read user data created in PostHog. This tool returns data that the user manually creates in PostHog.

# Data warehouse schema

Returns the SQL ClickHouse schema for the user's data warehouse.
You MUST use this tool when:
- Working with SQL.
- The request is about data warehouse, connected data sources, etc.

{{billing_prompt}}
""".strip()

BILLING_INSUFFICIENT_ACCESS_PROMPT = """
The user does not have admin access to view detailed billing information. They would need to contact an organization admin for billing details.
Suggest the user to contact the admins.
""".strip()

ReadDataKind = Literal["datawarehouse_schema"]
ReadDataAdminAccessKind = Literal["datawarehouse_schema", "billing_info"]


class ReadDataToolArgs(BaseModel):
    kind: ReadDataKind


class ReadDataAdminAccessToolArgs(BaseModel):
    kind: ReadDataAdminAccessKind


class ReadDataTool(HogQLDatabaseMixin, MaxTool):
    name: Literal["read_data"] = "read_data"
    description: str = READ_DATA_PROMPT
    context_prompt_template: str = "Reads user data created in PostHog (data warehouse schema, billing information)"
    args_schema: type[BaseModel] = ReadDataToolArgs

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
        """
        Factory that creates a ReadDataTool with a dynamic args schema.

        Override this factory to add additional args schemas or descriptions.
        """
        args: type[BaseModel] = ReadDataToolArgs
        if not context_manager:
            context_manager = AssistantContextManager(team, user, config)
        billing_prompt = ""
        if await context_manager.check_user_has_billing_access():
            args = ReadDataAdminAccessToolArgs
            billing_prompt = READ_DATA_BILLING_PROMPT
        description = format_prompt_string(READ_DATA_PROMPT, billing_prompt=billing_prompt)
        return cls(
            team=team,
            user=user,
            state=state,
            node_path=node_path,
            config=config,
            args_schema=args,
            description=description,
            context_manager=context_manager,
        )

    async def _arun_impl(self, kind: ReadDataAdminAccessKind | ReadDataKind) -> tuple[str, None]:
        match kind:
            case "billing_info":
                has_access = await self._context_manager.check_user_has_billing_access()
                if not has_access:
                    return BILLING_INSUFFICIENT_ACCESS_PROMPT, None
                # used for routing
                billing_tool = ReadBillingTool(
                    team=self._team,
                    user=self._user,
                    state=self._state,
                    config=self._config,
                    context_manager=self._context_manager,
                )
                result = await billing_tool.execute()
                return result, None
            case "datawarehouse_schema":
                return await self._serialize_database_schema(), None
