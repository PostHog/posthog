from unittest.mock import MagicMock, patch

from openai.types.create_embedding_response import CreateEmbeddingResponse, Usage
from openai.types.embedding import Embedding

from posthog.clickhouse.client.execute import sync_execute
from posthog.test.base import BaseTest
from products.editor.backend.chunking.parser import ProgrammingLanguage
from products.editor.backend.chunking.types import Chunk

from ..tasks import EmbeddingResult, insert_embeddings
from .base import EditorTestQueryHelpersMixin


class TestTasks(EditorTestQueryHelpersMixin, BaseTest):
    @patch("openai.OpenAI")
    def test_create_embeddings(self, openai_mock):
        # Set up the mock OpenAI client
        mock_client = MagicMock()
        openai_mock.return_value = mock_client

        embedding = [0.1, 0.2, 0.3]
        mock_response = CreateEmbeddingResponse(
            usage=Usage(prompt_tokens=100, total_tokens=100),
            model="test",
            data=[Embedding(index=0, embedding=embedding, object="embedding")],
            object="list",
        )

        # Configure the mock's embeddings.create method
        mock_client.embeddings.create.return_value = mock_response

        from ..tasks import chunk_and_embed

        res = chunk_and_embed("test = 1", ProgrammingLanguage.PYTHON)
        self.assertEqual(mock_client.embeddings.create.call_count, 1)
        self.assertEqual(
            res, [(Chunk(text="test", line_start=0, line_end=0, context="", content="test = 1"), embedding)]
        )

    @patch("openai.OpenAI")
    def test_create_embeddings_batches(self, openai_mock):
        # Set up the mock OpenAI client
        mock_client = MagicMock()
        openai_mock.return_value = mock_client

        embedding = [0.1, 0.2, 0.3]
        mock_response = CreateEmbeddingResponse(
            usage=Usage(prompt_tokens=100, total_tokens=100),
            model="test",
            data=[Embedding(index=0, embedding=embedding, object="embedding")],
            object="list",
        )

        # Configure the mock's embeddings.create method
        mock_client.embeddings.create.return_value = mock_response

        snippet = """
        @patch("openai.OpenAI")
        def test_create_embeddings(self, openai_mock):
            # Set up the mock OpenAI client
            mock_client = MagicMock()
            openai_mock.return_value = mock_client

            embedding = [0.1, 0.2, 0.3]
            mock_response = CreateEmbeddingResponse(
                usage=Usage(prompt_tokens=100, total_tokens=100),
                model="test",
                data=[Embedding(index=0, embedding=embedding, object="embedding")],
                object="list",
            )

            # Configure the mock's embeddings.create method
            mock_client.embeddings.create.return_value = mock_response

            from ..tasks import chunk_and_embed

            res = chunk_and_embed("test = 1", ProgrammingLanguage.PYTHON)
            self.assertEqual(mock_client.embeddings.create.call_count, 1)
            self.assertEqual(
                res, [(Chunk(text="test", line_start=0, line_end=0, context="", content="test = 1"), embedding)]
            )

            res = chunk_and_embed("test = 2", ProgrammingLanguage.PYTHON)
            self.assertEqual(mock_client.embeddings.create.call_count, 1)
            self.assertEqual(
                res, [(Chunk(text="test", line_start=0, line_end=0, context="", content="test = 2"), embedding)]
            )

            res = chunk_and_embed("test = 3", ProgrammingLanguage.PYTHON)
            self.assertEqual(mock_client.embeddings.create.call_count, 1)
            self.assertEqual(
                res, [(Chunk(text="test", line_start=0, line_end=0, context="", content="test = 3"), embedding)]
            )
        """

        from ..tasks import chunk_and_embed

        res = chunk_and_embed(snippet, ProgrammingLanguage.PYTHON, batch_size=1)
        self.assertEqual(len(res), 2)
        self.assertEqual(mock_client.embeddings.create.call_count, 2)

    def test_insert_embeddings(self):
        res: EmbeddingResult = [
            (Chunk(text="test", line_start=0, line_end=30, context="", content="test = 1"), [0.1, 0.2, 0.3]),
        ]
        insert_embeddings(self.team.id, self.user.id, "codebase", "artifact", "obfuscated_path", res)
        rows = sync_execute(
            "select team_id, user_id, codebase_id, artifact_id, chunk_id, vector, properties, is_deleted from codebase_embeddings",
            team_id=self.team.id,
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[0], self.team.id)
        self.assertEqual(row[1], self.user.id)
        self.assertEqual(row[2], "codebase")
        self.assertEqual(row[3], "artifact")
        self.assertEqual(row[4], "0")
        for place, expected in zip(row[5], [0.1, 0.2, 0.3]):
            self.assertAlmostEqual(place, expected, 1)
        self.assertEqual(row[6], '{"path": "obfuscated_path", "line_start": 0, "line_end": 30}')
        self.assertEqual(row[7], 0)
