import json

from celery import shared_task
from openai import OpenAI
from structlog import get_logger

from posthog.clickhouse.client import sync_execute
from products.editor.backend.chunking import chunk_text
from products.editor.backend.chunking.types import Chunk

logger = get_logger(__name__)

EmbeddingResult = list[tuple[Chunk, list[float]]]


def chunk_and_embed(file_path: str, file_content: str) -> EmbeddingResult:
    chunk = chunk_text(file_path, file_content)
    client = OpenAI()
    embeddings: list[tuple[Chunk, list[float]]] = []
    for batch_size in range(0, len(chunk), 2048):
        chunk_slice = chunk[batch_size : batch_size + 2048]
        response = client.embeddings.create(
            input=[chunk.text for chunk in chunk_slice],
            model="text-embedding-3-small",
        )
        for chunk, embedding_res in zip(chunk_slice, response.data):
            embeddings.append((chunk, embedding_res.embedding))

    return embeddings


def insert_embeddings(
    team_id: int,
    user_id: int,
    codebase_id: int,
    artifact_id: str,
    file_path: str,
    embeddings: EmbeddingResult,
):
    query = "INSERT INTO codebase_embeddings (team_id, user_id, codebase_id, artifact_id, chunk_id, vector, properties) VALUES "
    args = {
        "team_id": team_id,
        "user_id": user_id,
        "codebase_id": codebase_id,
        "artifact_id": artifact_id,
    }
    rows: list[str] = []

    for idx, (chunk, embedding) in enumerate(embeddings):
        args.update(
            {
                f"chunk_id_{idx}": str(idx),
                f"vector_{idx}": embedding,
                f"properties_{idx}": json.dumps(
                    {
                        "path": file_path,
                        "startLine": chunk.line_start,
                        "endLine": chunk.line_end,
                    }
                ),
            }
        )
        rows.append(
            f"(%(team_id)s, %(user_id)s, %(codebase_id)s, %(artifact_id)s, %(chunk_id_{idx})s, %(vector_{idx})s, %(properties_{idx})s)"
        )
    sync_execute(query + ", ".join(rows), args, team_id=team_id)


@shared_task(ignore_result=True, max_retries=5, retry_backoff=True, expires=60 * 10)
def embed_file(
    team_id: int,
    user_id: int,
    codebase_id: int,
    artifact_id: str,
    file_path: str,
    file_content: str,
):
    try:
        logger.info(
            "Embedding file",
            team_id=team_id,
            user_id=user_id,
            codebase_id=codebase_id,
            artifact_id=artifact_id,
        )
        embeddings = chunk_and_embed(file_path, file_content)
        insert_embeddings(team_id, user_id, codebase_id, artifact_id, file_path, embeddings)
    except Exception as e:
        logger.exception(
            "Error embedding file",
            team_id=team_id,
            user_id=user_id,
            codebase_id=codebase_id,
            artifact_id=artifact_id,
            error=type(e).__name__,
        )
        raise
