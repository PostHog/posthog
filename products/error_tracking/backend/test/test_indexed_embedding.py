from unittest import TestCase, mock

from parameterized import parameterized

from products.error_tracking.backend.indexed_embedding import AddVectorIndex

EXPERIMENTAL = {"allow_experimental_vector_similarity_index": "1"}
INDEX_SQL = (
    "ALTER TABLE sharded_embeddings ADD INDEX IF NOT EXISTS embedding_idx_cosine "
    "embedding TYPE vector_similarity('hnsw', 'cosineDistance', 1536)"
)


class TestAddVectorIndex(TestCase):
    index = AddVectorIndex(
        table_name="sharded_embeddings",
        index_name="embedding_idx_cosine",
        distance_function="cosineDistance",
        dimension=1536,
    )

    @parameterized.expand(
        [
            ("24.8.14.39", None, None),
            ("24.10.4.191", None, None),
            ("25.3.14.14", None, None),
            ("25.4.13.22", INDEX_SQL, EXPERIMENTAL),
            ("25.8.33.6", INDEX_SQL, None),
            ("26.6.2.158", INDEX_SQL, None),
        ]
    )
    def test_statement_matches_server_version(self, version, expected_sql, expected_settings):
        client = mock.MagicMock()
        client.execute.return_value = [(version,)]

        self.index(client)

        if expected_sql is None:
            client.execute.assert_called_once_with("SELECT version()")
        else:
            client.execute.assert_called_with(expected_sql, settings=expected_settings)
