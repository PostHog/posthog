"""
Message router for cloud agent sessions using Redis pub/sub.

Channels:
- cloud-session:{run_id}:to-agent - Messages from client to agent (pub/sub)
- cloud-session:{run_id}:from-agent - Events from agent to client (pub/sub)
- cloud-session:{run_id}:to-agent:queue - Queued messages when no subscriber
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from posthog.redis import get_async_client

logger = logging.getLogger(__name__)


class MessageRouter:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._to_agent_channel = f"cloud-session:{run_id}:to-agent"
        self._from_agent_channel = f"cloud-session:{run_id}:from-agent"
        self._to_agent_queue = f"cloud-session:{run_id}:to-agent:queue"

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to events from the agent for this run."""
        client = get_async_client()
        pubsub = client.pubsub()

        try:
            await pubsub.subscribe(self._from_agent_channel)
            logger.info(f"[ROUTER] Subscribed to {self._from_agent_channel}")

            async for message in pubsub.listen():
                logger.debug(f"[ROUTER] Raw Redis message type: {message['type']}")
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        logger.info(f"[ROUTER] Received from agent: method={data.get('method', 'unknown')}")
                        logger.debug(f"[ROUTER] Full data: {data}")
                        yield data
                    except json.JSONDecodeError:
                        logger.warning(f"[ROUTER] Failed to decode message: {message['data']}")
        finally:
            logger.info(f"[ROUTER] Unsubscribing from {self._from_agent_channel}")
            await pubsub.unsubscribe(self._from_agent_channel)
            await pubsub.close()

    async def publish_to_agent(self, message: dict[str, Any]) -> None:
        """Publish a message to the agent channel. Queues if no subscriber."""
        client = get_async_client()
        message_json = json.dumps(message)
        logger.info(f"[ROUTER] Publishing to {self._to_agent_channel}: method={message.get('method', 'unknown')}")

        result = await client.publish(self._to_agent_channel, message_json)
        logger.info(f"[ROUTER] Publish result (subscribers count): {result}")

        if result == 0:
            logger.info(f"[ROUTER] No subscribers, queueing message to {self._to_agent_queue}")
            await client.rpush(self._to_agent_queue, message_json)

    async def drain_queue(self) -> list[dict[str, Any]]:
        """Drain all queued messages (called by agent on startup)."""
        client = get_async_client()
        messages = []

        while True:
            message_json = await client.lpop(self._to_agent_queue)
            if message_json is None:
                break
            try:
                messages.append(json.loads(message_json))
            except json.JSONDecodeError:
                logger.warning(f"[ROUTER] Failed to decode queued message: {message_json}")

        if messages:
            logger.info(f"[ROUTER] Drained {len(messages)} queued messages")

        return messages

    async def publish_from_agent(self, event: dict[str, Any]) -> None:
        """Publish an event from the agent to clients."""
        client = get_async_client()
        await client.publish(self._from_agent_channel, json.dumps(event))
        logger.debug(f"Published from agent: {event.get('method', 'unknown')}")
