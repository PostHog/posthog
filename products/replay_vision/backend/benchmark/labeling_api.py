"""Read the labeling suite's benchmark export API, the one contract this benchmark has with MLHog.

The routes and their shapes are documented in MLHog's `labeling/replay/EXPORT.md`. Nothing here
knows the labeling database, the image ref formats or the v2 encryption; the playable route
returns a recording with all of that already resolved.
"""

import time
from collections import defaultdict
from typing import Any

from django.conf import settings

import requests
from pydantic import BaseModel

from products.replay_vision.backend.benchmark.consensus import CellConsensus, Question, cell_consensus
from products.replay_vision.backend.benchmark.layout import BenchmarkCase

EXPORT_SCHEMA_VERSION = 1
_PAGE_SIZE = 200
# A playable recording is decoded and image-resolved on request, so a long one takes a while.
_TIMEOUT = (10, 300)
# The app caps playable exports in flight and answers the overflow with a 429, which clears once
# another export finishes, so a busy answer is waited out here rather than failing the case.
_BUSY_RETRIES = 4
_BUSY_BACKOFF_SECONDS = 5


class ExportSnapshot(BaseModel, frozen=True):
    questions: list[Question]
    cells: list[CellConsensus]
    cases: list[BenchmarkCase]


class PlayableRecording(BaseModel, frozen=True):
    jsonl: bytes
    image_refs: int
    images_resolved: int


class LabelingExportClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base = base_url.rstrip("/") + "/v1/admin/exports/benchmark"
        self.headers = {"authorization": f"Bearer {token}", "user-agent": "posthog-replay-vision-benchmark"}

    @classmethod
    def from_settings(cls) -> "LabelingExportClient":
        if not settings.REPLAY_VISION_BENCHMARK_LABELING_URL or not settings.REPLAY_VISION_BENCHMARK_LABELING_TOKEN:
            raise ValueError("REPLAY_VISION_BENCHMARK_LABELING_URL and _TOKEN must be set")
        return cls(settings.REPLAY_VISION_BENCHMARK_LABELING_URL, settings.REPLAY_VISION_BENCHMARK_LABELING_TOKEN)

    def _get(self, path: str, params: dict[str, str] | None = None) -> requests.Response:
        for attempt in range(_BUSY_RETRIES + 1):
            response = requests.get(f"{self.base}{path}", params=params, headers=self.headers, timeout=_TIMEOUT)
            if response.status_code != 429 or attempt == _BUSY_RETRIES:
                break
            time.sleep(_BUSY_BACKOFF_SECONDS * 2**attempt)
        response.raise_for_status()
        return response

    def _json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        body = self._get(path, params).json()
        if body.get("schemaVersion") != EXPORT_SCHEMA_VERSION:
            raise ValueError(
                f"labeling export serves schema {body.get('schemaVersion')}, expected {EXPORT_SCHEMA_VERSION}"
            )
        return body

    def snapshot(self) -> ExportSnapshot:
        questions = self._json("/questions")["questions"]
        recordings: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            params = {"limit": str(_PAGE_SIZE)} | ({"after": after} if after else {})
            page = self._json("/recordings", params)
            recordings.extend(page["recordings"])
            after = page["next"]
            if after is None:
                return build_snapshot(questions, recordings)

    def playable(self, recording_id: str) -> PlayableRecording:
        # requests undoes the route's gzip content-encoding.
        response = self._get(f"/recordings/{recording_id}/playable")
        return PlayableRecording(
            jsonl=response.content,
            image_refs=int(response.headers.get("x-benchmark-image-refs", 0)),
            images_resolved=int(response.headers.get("x-benchmark-images-resolved", 0)),
        )


def build_snapshot(questions: list[dict[str, Any]], recordings: list[dict[str, Any]]) -> ExportSnapshot:
    """Consensus per (question, recording) cell for the v2 recordings, from answers to the question's current wording.

    An answer to an earlier version answered a different question, and one with no version predates the
    column, so neither can be pooled with the rest.
    """
    parsed = {
        row["questionId"]: Question(
            question_id=row["questionId"],
            version=row["version"],
            type=row["question"]["type"],
            definition=row["question"],
        )
        for row in questions
    }
    cells: list[CellConsensus] = []
    cases: list[BenchmarkCase] = []
    for recording in recordings:
        # A v1 recording's ids are pseudonyms, so no production inputs exist to scan it with.
        if recording["idKind"] != "real" or not (recording["teamRef"] or "").isdigit() or not recording["sessionRef"]:
            continue
        answers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for label in recording["labels"]:
            question = parsed.get(label["questionId"])
            if question is not None and label["questionVersion"] == question.version:
                answers[label["questionId"]].append(label["label"])
        recording_cells = [
            consensus
            for question_id in sorted(answers.keys() & parsed.keys())
            if (
                consensus := cell_consensus(
                    parsed[question_id],
                    recording["recordingId"],
                    answers[question_id],
                )
            )
            is not None
        ]
        if not recording_cells:
            continue
        cells.extend(recording_cells)
        cases.append(
            BenchmarkCase(
                case_id=recording["recordingId"],
                split=recording["split"],
                domain=recording["domain"],
                team_id=int(recording["teamRef"]),
                session_id=recording["sessionRef"],
                product_context=recording["siteBrief"] or "",
            )
        )
    return ExportSnapshot(questions=list(parsed.values()), cells=cells, cases=cases)
