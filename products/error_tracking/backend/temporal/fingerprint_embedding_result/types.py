import dataclasses

PREFERRED_EMBEDDING_MODEL = "text-embedding-3-large-3072"


def select_model_name(model_names: list[str]) -> str:
    if PREFERRED_EMBEDDING_MODEL in model_names:
        return PREFERRED_EMBEDDING_MODEL
    if model_names:
        return model_names[0]
    return PREFERRED_EMBEDDING_MODEL


@dataclasses.dataclass(frozen=True)
class FingerprintEmbeddingResultInputs:
    team_id: int
    fingerprint: str
    rendering: str
    timestamp: str
    model_name: str | None = None
    model_names: list[str] = dataclasses.field(default_factory=list)
    embedding: list[float] | None = None


@dataclasses.dataclass(frozen=True)
class SimilarFingerprintDistance:
    fingerprint: str
    distance: float


@dataclasses.dataclass(frozen=True)
class FingerprintEmbeddingMergeResult:
    merged_count: int = 0
    query_duration_ms: float | None = None
    closest_fingerprints: list[SimilarFingerprintDistance] = dataclasses.field(default_factory=list)
