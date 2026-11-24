"""Signal emitter for g2 `reviews` (record kind: review).

`answers` is a JSON object keyed by question slug, each value `{text, value}`. Most keys hold a
pick from a list (role, time used, deployment) or a number, so only the prose answers in
`PROSE_ANSWER_KEYS` reach the description, after the review title. `submitted_at` is an ISO
string. The country, region and reviewer columns are not read, because they identify the reviewer.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission._survey import parse_json
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

G2_FIELDS = ("id", "title", "answers", "star_rating", "product_name", "url", "submitted_at")

# What the reviewer likes, dislikes, recommends, and the problems the product solves for them.
PROSE_ANSWER_KEYS = ("love", "hate", "recommendations", "benefits")
MAX_DESCRIPTION_CHARS = 4000


def _prose_answers(raw: Any) -> list[str]:
    answers = parse_json(raw)
    if not isinstance(answers, dict):
        return []
    lines: list[str] = []
    for key in PROSE_ANSWER_KEYS:
        answer = answers.get(key)
        if not isinstance(answer, dict):
            continue
        value = answer.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        question = answer.get("text")
        lines.append(f"{question}: {value.strip()}" if isinstance(question, str) and question else value.strip())
    return lines


def g2_review_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        review_id = record["id"]
    except KeyError as e:
        msg = f"G2 review record missing required field {e}"
        logger.exception(msg, record_keys=list(record), team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not review_id:
        return None

    title = record.get("title")
    title = title.strip() if isinstance(title, str) else ""
    answers = _prose_answers(record.get("answers"))
    if not answers:
        logger.info("Ignoring G2 review without prose answers", team_id=team_id, signals_type="data-import-signals")
        return None

    description = "\n".join([title, *answers] if title else answers)[:MAX_DESCRIPTION_CHARS]
    extra = {
        field: None if record.get(field) is None else str(record.get(field))
        for field in ("star_rating", "product_name", "url", "submitted_at")
    }
    return SignalEmitterOutput(
        source_product="g2",
        source_type="review",
        source_id=str(review_id),
        description=description,
        weight=1.0,
        extra=extra,
    )


G2_CONFIG = SignalSourceTableConfig(
    source_product="g2",
    source_type="review",
    emitter=g2_review_emitter,
    unloggable_fields=("answers",),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="submitted_at",
    partition_field_is_datetime_string=True,
    fields=G2_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
