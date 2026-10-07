from __future__ import annotations

import os
import json
import math
import asyncio
import argparse
import subprocess
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid5

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from posthog.dataclasses import frozen

from .engines.types import CaseResult, ExperimentResult

ScorerKind = Literal["boolean", "numeric"]
MAX_BATCH_BYTES = 4 * 1024 * 1024
MAX_BATCH_RESULTS = 1000


@frozen
class OfflineEvalSuite:
    key: str
    scorer_kinds: Mapping[str, ScorerKind]


class OfflineUploadError(Exception):
    pass


class OfflineEvalSettings(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    host: str = "https://us.posthog.com"
    project_id: int = Field(gt=0)
    api_key: SecretStr
    scorer_versions: dict[str, UUID]

    @classmethod
    def from_env(cls, suite: OfflineEvalSuite | None = None) -> OfflineEvalSettings | None:
        prefix = "POSTHOG_OFFLINE_EVAL_"
        if not any(os.getenv(prefix + key) for key in ("API_KEY", "PROJECT_ID", "SCORER_VERSIONS", "HOST")):
            return None
        try:
            settings = cls(
                host=os.getenv(prefix + "HOST", "https://us.posthog.com").rstrip("/"),
                project_id=int(os.environ[prefix + "PROJECT_ID"]),
                api_key=SecretStr(os.environ[prefix + "API_KEY"]),
                scorer_versions=json.loads(os.environ[prefix + "SCORER_VERSIONS"]) if suite is not None else {},
            )
        except (KeyError, ValueError, ValidationError):
            raise OfflineUploadError(
                "Set POSTHOG_OFFLINE_EVAL_API_KEY, POSTHOG_OFFLINE_EVAL_PROJECT_ID and "
                "POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS (a JSON object of metric names to version UUIDs)"
            ) from None
        try:
            parsed = urlsplit(settings.host)
            _ = parsed.port
        except ValueError:
            raise OfflineUploadError("POSTHOG_OFFLINE_EVAL_HOST must be an HTTPS origin") from None
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise OfflineUploadError("POSTHOG_OFFLINE_EVAL_HOST must be an HTTPS origin")
        if not settings.api_key.get_secret_value().strip():
            raise OfflineUploadError("POSTHOG_OFFLINE_EVAL_API_KEY must not be empty")
        if suite is not None and set(settings.scorer_versions) != set(suite.scorer_kinds):
            raise OfflineUploadError("POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS must map every enrolled metric exactly once")
        if len(set(settings.scorer_versions.values())) != len(settings.scorer_versions):
            raise OfflineUploadError("Each offline metric must have a distinct scorer version UUID")
        return settings


def _encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _valid_payload(value: object, depth: int = 1) -> bool:
    if isinstance(value, dict):
        return depth <= 28 and all(
            isinstance(key, str) and "\x00" not in key and _valid_payload(child, depth + 1)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return depth <= 28 and all(_valid_payload(child, depth + 1) for child in value)
    if isinstance(value, str):
        return "\x00" not in value
    return value is None or type(value) in (bool, int, float)


class OfflineEvalPublisher:
    def __init__(self, settings: OfflineEvalSettings, suite: OfflineEvalSuite) -> None:
        self.settings = settings
        self.suite = suite

    def _item_payload(self, case: CaseResult, metadata: Mapping[str, object]) -> dict[str, object]:
        omitted: dict[str, object] = {}
        output = case.output
        if isinstance(output, dict):
            output = dict(output)
            if "raw_log" in output:
                output.pop("raw_log")
                omitted["output.raw_log"] = "available in local logs and Braintrust"
        payload: dict[str, object] = {}
        for key, value in (("input", case.input), ("output", output), ("expected_output", case.expected)):
            try:
                if not _valid_payload(value):
                    raise ValueError
                encoded = _encode(value)
                # Keep useful small artifacts when one tool response dominates the output.
                if key == "output" and isinstance(value, dict):
                    value = dict(value)
                    while len(encoded) > 256 * 1024 and value:
                        largest = max(value, key=lambda field: len(_encode(value[field])))
                        omitted[f"output.{largest}"] = {"bytes": len(_encode(value.pop(largest)))}
                        encoded = _encode(value)
                if len(encoded) > 256 * 1024:
                    omitted[key] = {"bytes": len(encoded)}
                else:
                    payload[key] = value
            except (ValueError, TypeError, UnicodeError):
                omitted[key] = "not supported by the offline payload API"
        item_metadata: dict[str, object] = dict(metadata)
        try:
            if not _valid_payload(case.metadata) or len(_encode(case.metadata)) > 64 * 1024:
                raise ValueError
            item_metadata["case"] = case.metadata
        except (ValueError, TypeError, UnicodeError):
            omitted["metadata.case"] = "invalid or exceeds 64 KiB"
        payload["metadata"] = {**item_metadata, "omitted_fields": omitted}
        return payload

    def _score(self, case: CaseResult, metric: str, item_id: str) -> dict[str, object]:
        result: dict[str, object] = {
            "item_id": item_id,
            "scorer_version_id": str(self.settings.scorer_versions[metric]),
        }
        if case.error is not None or metric not in case.scores:
            result.update(status="error", error_code="task_error" if case.error is not None else "missing_score")
            scorer_errors = case.metadata.get("scorer_errors", {})
            detail = case.error or (
                str(scorer_errors.get(metric, "Scorer did not return a result"))
                if isinstance(scorer_errors, dict)
                else "Scorer did not return a result"
            )
            result["payload"] = {"error_message": detail[:16000].replace("\x00", "")}
        elif (score := case.scores[metric]) is None:
            result["status"] = "skipped"
        elif (
            not math.isfinite(score)
            or not 0 <= score <= 1
            or (self.suite.scorer_kinds[metric] == "boolean" and score not in (0, 1))
        ):
            result.update(status="error", error_code="invalid_score")
            result["payload"] = {"error_message": "Scorer returned a value outside its configured domain"}
        else:
            result.update(
                status="ok", value=bool(score) if self.suite.scorer_kinds[metric] == "boolean" else float(score)
            )
        return result

    def prepare(
        self,
        *,
        experiment_id: str,
        experiment_name: str,
        started_at: datetime,
        result: ExperimentResult,
        metadata: Mapping[str, object],
    ) -> dict[str, object]:
        try:
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[3],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            revision = None
        experiment: dict[str, object] = {
            "id": experiment_id,
            "name": experiment_name,
            "started_at": started_at.isoformat(),
            "suite_key": self.suite.key,
            "run_source": "ci" if os.getenv("CI") else "local",
            "dataset_source": "repository",
            "dataset_identifier": self.suite.key,
            "dataset_revision_identifier": revision,
            "application_version": revision,
            "model_version": metadata.get("agent_model"),
            "expected_item_count": len(result.results),
            "expected_result_count": len(result.results) * len(self.suite.scorer_kinds),
        }
        trials: Counter[str] = Counter()
        batches: list[dict[str, object]] = []
        items: list[dict[str, object]] = []
        scores: list[dict[str, object]] = []
        for case in result.results:
            name = case.input["name"]
            trial = trials[name]
            trials[name] += 1
            item_id = str(uuid5(UUID(experiment_id), json.dumps([name, trial])))
            item = {
                "id": item_id,
                "case_key": name,
                "trial": str(trial),
                "payload": self._item_payload(
                    case, {**metadata, "braintrust_url": result.summary.experiment_url, "trial_index": trial}
                ),
            }
            case_scores = [self._score(case, metric, item_id) for metric in self.suite.scorer_kinds]
            candidate = {"items": [*items, item], "results": [*scores, *case_scores]}
            if items and (
                len(scores) + len(case_scores) > MAX_BATCH_RESULTS or len(_encode(candidate)) > MAX_BATCH_BYTES
            ):
                batches.append({"items": items, "results": scores})
                items, scores = [], []
            items.append(item)
            scores.extend(case_scores)
        if items:
            batches.append({"items": items, "results": scores})
        return {
            "host": self.settings.host,
            "project_id": self.settings.project_id,
            "experiment": experiment,
            "batches": batches,
        }

    async def _post(self, client: httpx.AsyncClient, path: str, body: object) -> None:
        encoded = _encode(body)
        for attempt in range(3):
            try:
                response = await client.post(path, content=encoded)
            except httpx.TransportError:
                if attempt == 2:
                    raise OfflineUploadError("PostHog upload failed after three network attempts") from None
                await asyncio.sleep(2**attempt)
                continue
            if response.is_success:
                return
            message = f"PostHog upload returned HTTP {response.status_code}"
            if response.status_code in (401, 403):
                message += "; check the key's offline_evaluation_ingestion:write scope and project access"
            if attempt == 2 or response.status_code not in (429, 500, 502, 503, 504):
                raise OfflineUploadError(message)
            try:
                delay = float(response.headers.get("Retry-After", 2**attempt))
            except ValueError:
                raise OfflineUploadError(message + "; retry later") from None
            if not 0 <= delay <= 30:
                raise OfflineUploadError(message + "; retry later")
            await asyncio.sleep(delay)

    async def publish(self, upload: dict[str, object]) -> str:
        if upload["host"] != self.settings.host or upload["project_id"] != self.settings.project_id:
            raise OfflineUploadError("Saved upload destination differs from the configured host/project")
        experiment = cast(dict[str, object], upload["experiment"])
        experiment_id = str(UUID(str(experiment["id"])))
        base = f"{self.settings.host}/api/projects/{self.settings.project_id}/ai_observability/offline_experiments/"
        async with httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.settings.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30, connect=5),
            follow_redirects=False,
        ) as client:
            await self._post(client, base, experiment)
            for batch in cast(list[dict[str, object]], upload["batches"]):
                await self._post(client, f"{base}{experiment_id}/upload/", batch)
            await self._post(client, f"{base}{experiment_id}/complete/", {})
        return (
            f"{self.settings.host}/project/{self.settings.project_id}"
            f"/ai-evals/evaluations/offline/experiments/{experiment_id}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry a saved offline upload without rerunning agents or scorers")
    parser.add_argument("upload", type=Path)
    args = parser.parse_args()
    try:
        settings = OfflineEvalSettings.from_env()
        if settings is None:
            raise OfflineUploadError("Set POSTHOG_OFFLINE_EVAL_API_KEY and POSTHOG_OFFLINE_EVAL_PROJECT_ID")
        upload = json.loads(args.upload.read_text())
        publisher = OfflineEvalPublisher(settings, OfflineEvalSuite(key="replay", scorer_kinds={}))
        url = asyncio.run(publisher.publish(upload))
    except (OfflineUploadError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Offline upload failed: {error}\n")
    parser.exit(0, f"PostHog: {url}\n")


if __name__ == "__main__":
    main()
