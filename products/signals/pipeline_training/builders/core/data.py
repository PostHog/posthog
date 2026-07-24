"""Load the downloaded signal universe into a pandas DataFrame.

The JSONL produced by download_signals.py is ~800MB and slow to parse, so the
first load flattens it into a parquet cache next to the source file; subsequent
loads take a couple of seconds. The cache is invalidated when the JSONL changes
(size + mtime).
"""

import os
import json
from typing import Any

import numpy as np
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
DEFAULT_JSONL = os.path.abspath(os.path.join(CACHE_DIR, "signals_team2.jsonl"))
DEFAULT_EMBEDDINGS_JSONL = os.path.abspath(os.path.join(CACHE_DIR, "signals_team2_embeddings.jsonl"))

# Flat columns extracted from each record; metadata fields are prefixed where ambiguous.
COLUMNS = [
    "document_id",
    "timestamp",
    "content",
    "source_product",
    "source_type",
    "source_id",
    "report_id",
    "weight",
]


def _cache_path(jsonl_path: str) -> str:
    stat = os.stat(jsonl_path)
    return f"{jsonl_path}.{stat.st_size}-{int(stat.st_mtime)}.parquet"


def _flatten(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") or {}
    return {
        "document_id": record["document_id"],
        "timestamp": record["timestamp"],
        "content": record["content"],
        "source_product": metadata.get("source_product"),
        "source_type": metadata.get("source_type"),
        "source_id": metadata.get("source_id"),
        "report_id": metadata.get("report_id"),
        "weight": metadata.get("weight"),
    }


def load_signals(jsonl_path: str = DEFAULT_JSONL, refresh: bool = False) -> pd.DataFrame:
    """Load the signal universe, sorted by timestamp (arrival order).

    Returns a DataFrame with columns: document_id, timestamp (datetime),
    content, source_product, source_type, source_id, report_id, weight,
    content_len.
    """
    cache = _cache_path(jsonl_path)
    if not refresh and os.path.exists(cache):
        return pd.read_parquet(cache)

    rows = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(_flatten(json.loads(line)))
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
    df["content_len"] = df["content"].str.len()
    df = df.sort_values("timestamp", ignore_index=True)

    # Clear older caches for this source before writing the fresh one.
    for stale in os.listdir(os.path.dirname(jsonl_path)):
        if stale.startswith(os.path.basename(jsonl_path) + ".") and stale.endswith(".parquet"):
            os.remove(os.path.join(os.path.dirname(jsonl_path), stale))
    df.to_parquet(cache)
    return df


def load_embeddings(jsonl_path: str = DEFAULT_EMBEDDINGS_JSONL, refresh: bool = False) -> tuple[pd.Index, np.ndarray]:
    """Load embedding vectors from an `--embeddings` download.

    Returns (document_ids, matrix) where matrix is float32 [n, dims], row i
    belonging to document_ids[i]. First load parses the multi-GB JSONL (slow);
    it's then cached as .npy + parquet next to the source file.
    """
    stat = os.stat(jsonl_path)
    stem = f"{jsonl_path}.{stat.st_size}-{int(stat.st_mtime)}"
    ids_cache, matrix_cache = f"{stem}.ids.parquet", f"{stem}.emb.npy"
    if not refresh and os.path.exists(ids_cache) and os.path.exists(matrix_cache):
        ids = pd.Index(pd.read_parquet(ids_cache)["document_id"])
        return ids, np.load(matrix_cache)

    id_list = []
    vectors = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                record = json.loads(line)
                id_list.append(record["document_id"])
                vectors.append(np.asarray(record["embedding"], dtype=np.float32))
    matrix = np.vstack(vectors)
    ids = pd.Index(id_list, name="document_id")

    directory = os.path.dirname(jsonl_path)
    base = os.path.basename(jsonl_path) + "."
    for stale in os.listdir(directory):
        if stale.startswith(base) and (stale.endswith(".ids.parquet") or stale.endswith(".emb.npy")):
            os.remove(os.path.join(directory, stale))
    pd.DataFrame({"document_id": id_list}).to_parquet(ids_cache)
    np.save(matrix_cache, matrix)
    return ids, matrix


def embeddings_for(df: pd.DataFrame, ids: pd.Index, matrix: np.ndarray) -> np.ndarray:
    """Align an embeddings matrix with a signals frame by document_id.

    Raises if any signal in `df` is missing an embedding — slice the frame to
    the intersection first if partial coverage is expected.
    """
    positions = ids.get_indexer(df["document_id"])
    if (positions < 0).any():
        missing = int((positions < 0).sum())
        raise ValueError(f"{missing} signals in the frame have no embedding in this file")
    return matrix[positions]


def load_raw_metadata(jsonl_path: str = DEFAULT_JSONL) -> "pd.Series":
    """Full metadata dicts keyed by document_id, for fields not in the flat frame."""
    ids = []
    metas = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                record = json.loads(line)
                ids.append(record["document_id"])
                metas.append(record.get("metadata") or {})
    return pd.Series(metas, index=ids, name="metadata")
