import json
from typing import cast

from posthog.schema import AssistantEventType, AssistantGenerationStatusEvent, AssistantUpdateEvent

from products.enterprise.backend.hogai.api.serializers import ConversationMinimalSerializer
from products.enterprise.backend.hogai.utils.types import AssistantMessageUnion, AssistantOutput
from products.enterprise.backend.models.assistant import Conversation


class AssistantSSESerializer:
    def dumps(self, event: AssistantOutput) -> str:
        event_type, event_data = event
        if event_type == AssistantEventType.MESSAGE:
            return self._serialize_message(cast(AssistantMessageUnion, event_data))
        elif event_type == AssistantEventType.CONVERSATION:
            return self._serialize_conversation(cast(Conversation, event_data))
        elif event_type == AssistantEventType.STATUS:
            return self._serialize_status(cast(AssistantGenerationStatusEvent, event_data))
        elif event_type == AssistantEventType.UPDATE:
            return self._serialize_update(cast(AssistantUpdateEvent, event_data))
        else:
            raise ValueError(f"Unknown event type: {event_type}")

    def _serialize_message(self, message: AssistantMessageUnion) -> str:
        output = f"event: {AssistantEventType.MESSAGE}\n"
        output += f"data: {message.model_dump_json(exclude_none=True)}\n\n"
        return output

    def _serialize_status(self, status: AssistantGenerationStatusEvent) -> str:
        output = f"event: {AssistantEventType.STATUS}\n"
        output += f"data: {status.model_dump_json(exclude_none=True)}\n\n"
        return output

    def _serialize_update(self, update: AssistantUpdateEvent) -> str:
        output = f"event: {AssistantEventType.UPDATE}\n"
        output += f"data: {update.model_dump_json(exclude_none=True)}\n\n"
        return output

    def _serialize_conversation(self, conversation: Conversation) -> str:
        output = f"event: {AssistantEventType.CONVERSATION}\n"
        json_conversation = json.dumps(ConversationMinimalSerializer(conversation).data)
        output += f"data: {json_conversation}\n\n"
        return output
