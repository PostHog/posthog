from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import HumanMessage

from products.enterprise.backend.hogai.graph.base import AssistantNode
from products.enterprise.backend.hogai.graph.title_generator.prompts import TITLE_GENERATION_PROMPT
from products.enterprise.backend.hogai.llm import MaxChatOpenAI
from products.enterprise.backend.hogai.utils.helpers import find_last_message_of_type
from products.enterprise.backend.hogai.utils.types import AssistantState, PartialAssistantState
from products.enterprise.backend.hogai.utils.types.base import AssistantNodeName
from products.enterprise.backend.hogai.utils.types.composed import MaxNodeName
from products.enterprise.backend.models.assistant import Conversation


class TitleGeneratorNode(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.TITLE_GENERATOR

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        human_message = find_last_message_of_type(state.messages, HumanMessage)
        if not human_message:
            return None

        conversation = self._get_conversation(config["configurable"]["thread_id"])
        if not conversation or conversation.title:
            return None

        runnable = (
            ChatPromptTemplate.from_messages([("system", TITLE_GENERATION_PROMPT), ("user", "{user_input}")])
            | self._model
            | StrOutputParser()
        )

        title = runnable.invoke({"user_input": human_message.content}, config=config)

        conversation.title = title[: Conversation.TITLE_MAX_LENGTH].strip()
        conversation.save()

        return None

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-4.1-nano",
            temperature=0.7,
            max_completion_tokens=100,
            user=self._user,
            team=self._team,
            streaming=False,
            stream_usage=False,
            disable_streaming=True,
        )
