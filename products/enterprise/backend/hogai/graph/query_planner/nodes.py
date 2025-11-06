from abc import ABC
from functools import cached_property
from typing import Literal, cast

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    ToolMessage as LangchainToolMessage,
    merge_message_runs,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import Field, ValidationError, create_model

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    VisualizationMessage,
)

from posthog.hogql.ai import SCHEMA_MESSAGE
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.models.group_type_mapping import GroupTypeMapping

from products.enterprise.backend.hogai.graph.base import AssistantNode
from products.enterprise.backend.hogai.graph.mixins import TaxonomyUpdateDispatcherNodeMixin
from products.enterprise.backend.hogai.graph.shared_prompts import CORE_MEMORY_PROMPT
from products.enterprise.backend.hogai.llm import MaxChatOpenAI
from products.enterprise.backend.hogai.utils.helpers import dereference_schema, format_events_yaml
from products.enterprise.backend.hogai.utils.types import AssistantState, PartialAssistantState
from products.enterprise.backend.hogai.utils.types.base import AssistantNodeName
from products.enterprise.backend.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    ACTIONS_EXPLANATION_PROMPT,
    EVENT_DEFINITIONS_PROMPT,
    HUMAN_IN_THE_LOOP_PROMPT,
    ITERATION_LIMIT_PROMPT,
    PROPERTY_FILTERS_EXPLANATION_PROMPT,
    QUERY_PLANNER_STATIC_SYSTEM_PROMPT,
    REACT_HELP_REQUEST_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
)
from .toolkit import (
    TaxonomyAgentTool,
    TaxonomyAgentToolkit,
    ask_user_for_help,
    final_answer,
    retrieve_action_properties,
    retrieve_action_property_values,
    retrieve_event_properties,
    retrieve_event_property_values,
)


class QueryPlannerNode(TaxonomyUpdateDispatcherNodeMixin, AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.QUERY_PLANNER

    def _get_dynamic_entity_tools(self):
        """Create dynamic Pydantic models with correct entity types for this team."""
        # Create Literal type with actual entity names
        DynamicEntityLiteral = Literal["person", "session", *self._team_group_types]  # type: ignore
        # Create dynamic retrieve_entity_properties model
        retrieve_entity_properties_dynamic = create_model(
            "retrieve_entity_properties",
            entity=(
                DynamicEntityLiteral,
                Field(..., description="The type of the entity that you want to retrieve properties for."),
            ),
            __doc__="""
            Use this tool to retrieve property names for a property group (entity). You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

            - **Infer the property groups from the user's request.**
            - **Try other entities** if the tool doesn't return any properties.
            - **Prioritize properties that are directly related to the context or objective of the user's query.**
            - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
            """,
        )
        # Create dynamic retrieve_entity_property_values model
        retrieve_entity_property_values_dynamic = create_model(
            "retrieve_entity_property_values",
            entity=(
                DynamicEntityLiteral,
                Field(..., description="The type of the entity that you want to retrieve properties for."),
            ),
            property_name=(
                str,
                Field(..., description="The name of the property that you want to retrieve values for."),
            ),
            __doc__="""
            Use this tool to retrieve property values for a property name. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
            """,
        )

        return retrieve_entity_properties_dynamic, retrieve_entity_property_values_dynamic

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        self.dispatch_update_message(state)
        conversation = self._construct_messages(state)

        chain = conversation | merge_message_runs() | self._get_model(state)

        events_in_context = []
        if ui_context := self.context_manager.get_ui_context(state):
            events_in_context = ui_context.events if ui_context.events else []

        output_message = chain.invoke(
            {
                "core_memory": self.core_memory.text if self.core_memory else "",
                "react_property_filters": self._get_react_property_filters_prompt(),
                "react_human_in_the_loop": HUMAN_IN_THE_LOOP_PROMPT,
                "groups": self._team_group_types,
                "events": format_events_yaml(events_in_context, self._team),
                "project_datetime": self.project_now,
                "project_timezone": self.project_timezone,
                "project_name": self._team.name,
                "organization_name": self._team.organization.name,
                "user_full_name": self._user.get_full_name(),
                "user_email": self._user.email,
                "actions": state.rag_context,
                "actions_prompt": ACTIONS_EXPLANATION_PROMPT,
                "trends_json_schema": dereference_schema(AssistantTrendsQuery.model_json_schema()),
                "funnel_json_schema": dereference_schema(AssistantFunnelsQuery.model_json_schema()),
                "retention_json_schema": dereference_schema(AssistantRetentionQuery.model_json_schema()),
            },
            config,
        )

        if not output_message.tool_calls:
            raise ValueError("No tool calls found in the output message.")

        tool_call = output_message.tool_calls[0]
        result = AgentAction(tool_call["name"], tool_call["args"], tool_call["id"])

        intermediate_steps = state.intermediate_steps or []
        return PartialAssistantState(
            intermediate_steps=[*intermediate_steps, (result, None)],
            query_planner_intermediate_messages=[*(state.query_planner_intermediate_messages or []), output_message],
        )

    def _get_model(self, state: AssistantState):
        # Get dynamic entity tools with correct types for this team
        dynamic_retrieve_entity_properties, dynamic_retrieve_entity_property_values = self._get_dynamic_entity_tools()

        return MaxChatOpenAI(
            model="o4-mini",
            use_responses_api=True,
            streaming=False,
            reasoning={
                "summary": "auto",  # Without this, there's no reasoning summaries! Only works with reasoning models
            },
            include=["reasoning.encrypted_content"],
            team=self._team,
            user=self._user,
            # LangChain sometimes incorrectly handles reasoning items. They fixed it in the new output version.
            # Ref: https://forum.langchain.com/t/langgraph-openai-responses-api-400-error-web-search-call-was-provided-without-its-required-reasoning-item/1740/2
            output_version="responses/v1",
            disable_streaming=True,
        ).bind_tools(
            [
                retrieve_event_properties,
                retrieve_action_properties,
                dynamic_retrieve_entity_properties,
                retrieve_event_property_values,
                retrieve_action_property_values,
                dynamic_retrieve_entity_property_values,
                ask_user_for_help,
                final_answer,
            ],
            tool_choice="required",
            parallel_tool_calls=False,
        )

    def _get_react_property_filters_prompt(self) -> str:
        return cast(
            str,
            ChatPromptTemplate.from_template(PROPERTY_FILTERS_EXPLANATION_PROMPT, template_format="mustache")
            .format_messages(groups=self._team_group_types)[0]
            .content,
        )

    @cached_property
    def _team_group_types(self) -> list[str]:
        return list(
            GroupTypeMapping.objects.filter(project_id=self._team.project_id)
            .order_by("group_type_index")
            .values_list("group_type", flat=True)
        )

    def _construct_messages(self, state: AssistantState) -> ChatPromptTemplate:
        """
        Construct the conversation thread for the agent. Handles both initial conversation setup
        and continuation with intermediate steps.
        """
        # Initial conversation setup
        database = Database.create_for(team=self._team)
        serialized_database = database.serialize(
            HogQLContext(team=self._team, enable_select_queries=True, database=database)
        )
        hogql_schema_description = "\n\n".join(
            (
                f"Table `{table_name}` with fields:\n"
                + "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())
                for table_name, table in serialized_database.items()
                # Only the most important core tables, plus all warehouse tables
                if table_name in ["events", "groups", "persons"] or table_name in database.get_warehouse_table_names()
            )
        )
        conversation = ChatPromptTemplate(
            [
                (
                    "system",
                    [
                        {"type": "text", "text": QUERY_PLANNER_STATIC_SYSTEM_PROMPT},
                        {
                            "type": "text",
                            "text": SCHEMA_MESSAGE.format(schema_description=hogql_schema_description),
                        },
                        {"type": "text", "text": CORE_MEMORY_PROMPT},
                        {"type": "text", "text": EVENT_DEFINITIONS_PROMPT},
                    ],
                ),
                # Include inputs and plans for up to 10 previously generated insights in thread
                *[
                    item
                    for message in state.messages
                    if isinstance(message, VisualizationMessage)
                    for item in [
                        ("human", message.query or "_No query description provided._"),
                        ("assistant", message.plan or "_No generated plan._"),
                    ]
                ][-20:],
                # The description of a new insight is added to the end of the conversation.
                ("human", state.root_tool_insight_plan or "_No query description provided._"),
            ],
            template_format="mustache",
        ) + (state.query_planner_intermediate_messages or [])

        return conversation


class QueryPlannerToolsNode(AssistantNode, ABC):
    MAX_ITERATIONS = 16
    """
    Maximum number of iterations for the ReAct agent. After the limit is reached,
    the agent will terminate the conversation and return a message to the root node
    to request additional information.
    """

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.QUERY_PLANNER_TOOLS

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = TaxonomyAgentToolkit(self._team)
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]

        input = None
        output = ""

        try:
            input = TaxonomyAgentTool.model_validate({"name": action.tool, "arguments": action.tool_input})
        except ValidationError as e:
            output = str(
                ChatPromptTemplate.from_template(REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
        else:
            # First check if we've reached the terminal stage.
            # The plan has been found. Move to the generation.
            if input.name == "final_answer":
                return PartialAssistantState(
                    plan=input.arguments.plan,  # type: ignore
                    root_tool_insight_type=input.arguments.query_kind,  # type: ignore
                    query_planner_previous_response_id=None,
                    intermediate_steps=None,
                    query_planner_intermediate_messages=None,
                )

            # The agent has requested help, so we return a message to the root node.
            if input.name == "ask_user_for_help":
                return self._get_reset_state(state, REACT_HELP_REQUEST_PROMPT.format(request=input.arguments))

        # If we're still here, the final prompt hasn't helped.
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(state, ITERATION_LIMIT_PROMPT)

        if input and not output:
            output = self._handle_tool(input, toolkit)

        return PartialAssistantState(
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
            query_planner_intermediate_messages=[
                *(state.query_planner_intermediate_messages or []),
                LangchainToolMessage(output, tool_call_id=action.log),
            ],
        )

    def router(self, state: AssistantState):
        # The plan has been found. Move to the generation.
        if state.plan:
            return state.root_tool_insight_type
        # Human-in-the-loop. Get out of the product analytics subgraph.
        if not state.root_tool_call_id:
            return "end"
        return "continue"

    def _handle_tool(self, input: TaxonomyAgentTool, toolkit: TaxonomyAgentToolkit) -> str:
        if input.name == "retrieve_event_properties":
            output = toolkit.retrieve_event_or_action_properties(input.arguments.event_name)  # type: ignore
        elif input.name == "retrieve_action_properties":
            output = toolkit.retrieve_event_or_action_properties(input.arguments.action_id)  # type: ignore
        elif input.name == "retrieve_event_property_values":
            output = toolkit.retrieve_event_or_action_property_values(
                input.arguments.event_name,  # type: ignore
                input.arguments.property_name,  # type: ignore
            )
        elif input.name == "retrieve_action_property_values":
            output = toolkit.retrieve_event_or_action_property_values(
                input.arguments.action_id,  # type: ignore
                input.arguments.property_name,  # type: ignore
            )
        elif input.name == "retrieve_entity_properties":
            output = toolkit.retrieve_entity_properties(input.arguments.entity)  # type: ignore
        elif input.name == "retrieve_entity_property_values":
            output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)  # type: ignore
        else:
            output = toolkit.handle_incorrect_response(input)
        return output

    def _get_reset_state(self, state: AssistantState, output: str):
        reset_state = PartialAssistantState.get_reset_state()
        reset_state.messages = [
            AssistantToolCallMessage(
                tool_call_id=state.root_tool_call_id,
                content=output,
            )
        ]
        return reset_state
