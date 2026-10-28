from posthog.schema_enums import EmbeddingModelName

# Signals writes one embedding row per model in this tuple, and spend metadata requires every one of those rows.
# Do not derive it from EmbeddingModelName: other products add models whose tables expire sooner,
# and the embedding worker rejects a whole request that names a model it does not support.
SIGNALS_EMBEDDING_MODELS: tuple[EmbeddingModelName, ...] = (
    EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536,
    EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072,
)

SIGNALS_FIRST_REPORT_EMAIL_TEMPLATE_ID: str = "01a1598d-9186-0000-b20d-d91813fc05ff"

FIRST_REPORT_SCOUT = "signals-scout-first-report"
SYSTEM_SCOUT_NAMES = frozenset({FIRST_REPORT_SCOUT})
FIRST_REPORT_SCOUT_TIMEOUT_SECONDS = 10 * 60


def first_report_idempotency_key(team_id: int) -> str:
    return f"first-report:{team_id}"
