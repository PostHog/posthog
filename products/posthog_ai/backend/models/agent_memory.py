from typing import TYPE_CHECKING

from django.db import models

from posthog.helpers.tiktoken_encoding import TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model
from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.kafka_client.client import ProduceResult

EMBEDDING_MODEL_TOKEN_LIMIT = 8192


class AgentMemory(UUIDModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="agent_memories",
    )
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_memories",
    )
    contents = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "id"]),
        ]

    def embed(self, model_name: str) -> "ProduceResult":
        enc = get_tiktoken_encoding_for_model(TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL)
        token_count = len(enc.encode(self.contents))
        if token_count > EMBEDDING_MODEL_TOKEN_LIMIT:
            raise ValueError(
                f"Memory content exceeds {EMBEDDING_MODEL_TOKEN_LIMIT} token limit for embedding model (got {token_count} tokens)"
            )

        from posthog.api.embedding_worker import emit_embedding_request

        embedding_metadata = {**self.metadata}
        if self.user_id is not None:
            embedding_metadata["user_id"] = str(self.user_id)

        return emit_embedding_request(
            content=self.contents,
            team_id=self.team_id,
            product="posthog-ai",
            document_type="memory",
            rendering="plaintext",
            document_id=str(self.id),
            models=[model_name],
            timestamp=self.created_at,
            metadata=embedding_metadata,
        )
