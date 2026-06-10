import dataclasses


@dataclasses.dataclass(frozen=True)
class FingerprintEmbeddingResultInputs:
    team_id: int
    fingerprint: str
    rendering: str
    timestamp: str
    model_names: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class SimilarFingerprintDistance:
    fingerprint: str
    distance: float


@dataclasses.dataclass(frozen=True)
class FingerprintEmbeddingMergeResult:
    merged_count: int = 0
    query_duration_ms: float | None = None
    closest_fingerprints: list[SimilarFingerprintDistance] = dataclasses.field(default_factory=list)
