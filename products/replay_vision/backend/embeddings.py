"""Embedding identity shared by the write side (embed_observation) and the search side (max_tools).

A search only finds rows written with the same (model, product, document_type) triple, so both sides must
import from here rather than defining their own copies.
"""

from posthog.schema import EmbeddingModelName

OBSERVATION_EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
EMBEDDING_PRODUCT = "replay-vision"
EMBEDDING_DOCUMENT_TYPE = "replay-observation"
