from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

import numpy as np
from asgiref.sync import async_to_sync

from posthog.api.embedding_worker import EmbeddingResponse

from products.mcp_analytics.backend.facade.api import cluster_texts


class TestClusterTexts(BaseTest):
    def test_labels_stay_aligned_with_texts_when_one_embedding_fails(self) -> None:
        embeddings = np.array([[1.0, 0.0], [1.0, 0.01], [0.0, 1.0]], dtype=np.float32)
        embed = AsyncMock(return_value=(embeddings, [0, 2, 3]))

        with patch("products.mcp_analytics.backend.intent_clustering.embed_texts_async", embed):
            labels = async_to_sync(cluster_texts)(self.team, ["signups", "broken", "new signups", "error rate"])

        assert labels[1] is None
        assert labels[0] == labels[2]
        assert labels[3] not in (None, labels[0])

    def test_reads_and_writes_the_embedding_cache_without_a_team_scope(self) -> None:
        texts = ["signups", "new signups", "error rate"]

        async def embed(team: object, content: str, model: str | None = None) -> EmbeddingResponse:
            vector = [1.0, 0.0] if "signups" in content else [0.0, 1.0]
            return EmbeddingResponse(embedding=vector, tokens_used=1, did_truncate=False)

        generate = AsyncMock(side_effect=embed)
        with patch("products.mcp_analytics.backend.intent_clustering.async_generate_embedding", generate):
            first = async_to_sync(cluster_texts)(self.team, texts)
            second = async_to_sync(cluster_texts)(self.team, texts)

        assert first == second
        assert first[0] == first[1] != first[2]
        assert generate.await_count == len(texts)
