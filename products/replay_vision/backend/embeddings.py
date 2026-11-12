"""Embedding identity shared by the write side (embed_observation) and the search side (max_tools).

A search only finds rows written with the same (model, product, document_type) triple, so both sides must
import from here rather than defining their own copies.
"""

from typing import Any

from posthog.schema import EmbeddingModelName

OBSERVATION_EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
EMBEDDING_PRODUCT = "replay-vision"
EMBEDDING_DOCUMENT_TYPE = "replay-observation"

# The physical table, read directly because the HogQL table pushes only the team filter down to storage.
OBSERVATION_EMBEDDINGS_TABLE = (
    f"distributed_posthog_document_embeddings_{OBSERVATION_EMBEDDING_MODEL.value.replace('-', '_')}"
)

# All of one team's observation embeddings; bind its values with `team_embeddings_params`.
TEAM_EMBEDDINGS_PREWHERE = """team_id = %(team_id)s
              AND product = %(product)s
              AND document_type = %(document_type)s"""

# One team's observation embeddings from the given scanners; bind its values with `observation_scope_params`.
OBSERVATION_SCOPE_PREWHERE = f"""{TEAM_EMBEDDINGS_PREWHERE}
              AND JSONExtractString(metadata, 'scanner_id') IN %(scanner_ids)s"""


def team_embeddings_params(team_id: int) -> dict[str, Any]:
    return {"team_id": team_id, "product": EMBEDDING_PRODUCT, "document_type": EMBEDDING_DOCUMENT_TYPE}


def observation_scope_params(team_id: int, scanner_ids: list[str]) -> dict[str, Any]:
    return {**team_embeddings_params(team_id), "scanner_ids": scanner_ids}
