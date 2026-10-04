"""Where a benchmark version's objects live. A version is written once and never edited; a refresh is a new version."""

import hashlib
from collections.abc import Iterable

from django.conf import settings

from pydantic import BaseModel, Field

# The fast tier's size: a fixed sample of a version's built cases, for iterating on a prompt.
FAST_TIER_SIZE = 50


def sample_case_ids(case_ids: Iterable[str], size: int) -> list[str]:
    """A fixed sample in hash order, so a small set is a sample rather than the oldest recordings."""
    return sorted(sorted(case_ids, key=lambda case_id: hashlib.sha256(case_id.encode()).hexdigest())[:size])


class BenchmarkCase(BaseModel, frozen=True):
    """One labeled recording to render, as listed in the version's `cases.jsonl`."""

    # The labeling suite's recording id, used as the case id throughout. It lands in object keys and workflow ids,
    # so only a UUID from the export is accepted.
    case_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    split: str | None
    domain: str | None
    # The PostHog team and session: production's scan inputs are fetched by them, and a deletion reaches the case by them.
    team_id: int
    session_id: str
    product_context: str = ""


class BenchmarkLayout:
    def __init__(self, version: str, *, bucket: str | None = None, prefix: str | None = None) -> None:
        self.bucket = settings.REPLAY_VISION_BENCHMARK_BUCKET if bucket is None else bucket
        self.root = f"{settings.REPLAY_VISION_BENCHMARK_PREFIX if prefix is None else prefix}/{version}"

    @property
    def manifest_key(self) -> str:
        return f"{self.root}/manifest.json"

    @property
    def questions_key(self) -> str:
        return f"{self.root}/questions.json"

    @property
    def labels_key(self) -> str:
        return f"{self.root}/labels.jsonl"

    @property
    def cases_key(self) -> str:
        return f"{self.root}/cases.jsonl"

    def case_prefix(self, case_id: str) -> str:
        return f"{self.root}/cases/{case_id}"

    def events_key(self, case_id: str) -> str:
        return f"{self.case_prefix(case_id)}/events.jsonl.zst"

    def inputs_key(self, case_id: str) -> str:
        return f"{self.case_prefix(case_id)}/inputs.json"

    def status_key(self, case_id: str) -> str:
        return f"{self.case_prefix(case_id)}/status.json"

    def events_uri(self, case_id: str) -> str:
        return f"s3://{self.bucket}/{self.events_key(case_id)}"
