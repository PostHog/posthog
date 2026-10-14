from __future__ import annotations

import os
import json
import asyncio
import argparse
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from posthoganalytics.ai.evaluations import (
    AsyncOfflineEvaluations,
    EvaluationAPIError,
    EvaluationItem,
    EvaluationResult,
    ExperimentOptions,
    JSONValue,
    ResultOptions,
    ScorerKind,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from posthog.dataclasses import frozen

from .engines.types import CaseResult, ExperimentResult, ScorerResult


@frozen
class OfflineEvalSuite:
    key: str
    scorer_kinds: Mapping[str, ScorerKind]
    experiment_options: ExperimentOptions = field(default_factory=lambda: ExperimentOptions())


class OfflineUploadError(Exception):
    pass


class OfflineEvalSettings(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    host: str = "https://us.posthog.com"
    project_id: int = Field(gt=0)
    api_key: SecretStr
    scorer_versions: dict[str, UUID]
    request_timeout: float = Field(default=15, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=3, ge=0)

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
        if suite is not None:
            if not set(suite.scorer_kinds) <= set(settings.scorer_versions):
                raise OfflineUploadError("POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS must map every enrolled metric")
            enrolled_versions = [settings.scorer_versions[metric] for metric in suite.scorer_kinds]
            if len(set(enrolled_versions)) != len(enrolled_versions):
                raise OfflineUploadError("Each offline metric must have a distinct scorer version UUID")
        return settings


def _encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object in the saved offline upload")
    return cast(dict[str, object], value)


def _records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("Expected a list in the saved offline upload")
    return [_object(record) for record in value]


@frozen
class OfflineEvalUpload:
    host: str
    project_id: int
    experiment_name: str
    experiment: ExperimentOptions
    items: tuple[EvaluationItem, ...]
    results: tuple[EvaluationResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "host": self.host,
            "project_id": self.project_id,
            "experiment": {"name": self.experiment_name, **self.experiment},
            "items": [item.to_dict() for item in self.items],
            "results": [result.to_dict() for result in self.results],
        }

    def save(self, path: Path) -> None:
        encoded = _encode(self.to_dict())
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as pending:
            temporary_path = Path(pending.name)
            try:
                pending.write(encoded)
                pending.flush()
                os.fsync(pending.fileno())
                pending.close()
                temporary_path.replace(path)
            finally:
                temporary_path.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> OfflineEvalUpload:
        document = _object(json.loads(path.read_bytes()))
        if document.get("version") not in (None, 1):
            raise OfflineUploadError("Unsupported saved offline upload version")
        experiment = _object(document["experiment"]).copy()
        name = experiment.pop("name")
        host, project_id = document["host"], document["project_id"]
        if not isinstance(name, str) or not isinstance(host, str) or type(project_id) is not int:
            raise ValueError("Invalid saved offline upload destination or experiment name")
        if "id" not in experiment or "started_at" not in experiment:
            raise ValueError("Saved offline uploads must retain their original experiment ID and start time")
        if "batches" in document:
            batches = _records(document["batches"])
            item_records = [item for batch in batches for item in _records(batch["items"])]
            result_records = [result for batch in batches for result in _records(batch["results"])]
        else:
            item_records = _records(document["items"])
            result_records = _records(document["results"])
        items: dict[str, EvaluationItem] = {}
        for record in item_records:
            item = EvaluationItem.from_dict(record)
            if item.id in items and item.to_dict() != items[item.id].to_dict():
                raise ValueError("Conflicting item declarations in the saved offline upload")
            items[item.id] = item
        results = tuple(
            EvaluationResult.from_dict(record, item=items[str(record["item_id"])]) for record in result_records
        )
        return cls(
            host=host,
            project_id=project_id,
            experiment_name=name,
            experiment=cast(ExperimentOptions, experiment),
            items=tuple(items.values()),
            results=results,
        )


class OfflineEvalPublisher:
    def __init__(
        self,
        settings: OfflineEvalSettings,
        suite: OfflineEvalSuite,
        *,
        application_trace_ids_enabled: bool = False,
    ) -> None:
        self.settings = settings
        self.suite = suite
        self.application_trace_ids_enabled = application_trace_ids_enabled

    def _item_payload(self, case: CaseResult, metadata: Mapping[str, object]) -> dict[str, JSONValue]:
        omitted: dict[str, JSONValue] = {}
        output = case.output
        if isinstance(output, dict):
            output = dict(output)
            if "raw_log" in output:
                output.pop("raw_log")
                omitted["output.raw_log"] = "available in local logs and Braintrust"
        payload: dict[str, JSONValue] = {}
        for key, value in (("input", case.input), ("output", output), ("expected_output", case.expected)):
            try:
                encoded = _encode(value)
                if key == "output" and isinstance(value, dict):
                    value = dict(value)
                    while len(encoded) > 256 * 1024 and value:
                        largest = max(value, key=lambda name: len(_encode(value[name])))
                        omitted[f"output.{largest}"] = {"bytes": len(_encode(value.pop(largest)))}
                        encoded = _encode(value)
                if len(encoded) > 256 * 1024:
                    omitted[key] = {"bytes": len(encoded)}
                else:
                    EvaluationItem(payload={key: value})
                    payload[key] = value
            except (ValueError, TypeError, UnicodeError, RecursionError):
                omitted[key] = "not supported by the offline payload API"
        item_metadata: dict[str, JSONValue] = {}
        for key, value in {**metadata, "case": case.metadata}.items():
            try:
                EvaluationItem(metadata={key: cast(JSONValue, value)})
                if len(_encode(value)) > 64 * 1024:
                    raise ValueError
                item_metadata[key] = cast(JSONValue, value)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                omitted[f"metadata.{key}"] = "invalid or exceeds 64 KiB"
        payload["metadata"] = {**item_metadata, "omitted_fields": omitted}
        return payload

    def _outcome(self, case: CaseResult, metric: str) -> ScorerResult:
        if case.error is not None:
            return ScorerResult(status="error", error_code="task_error", error_message=case.error)
        if metric in case.scorer_results:
            return case.scorer_results[metric]
        if metric not in case.scores:
            scorer_errors = case.metadata.get("scorer_errors", {})
            detail = (
                str(scorer_errors.get(metric, "Scorer did not return a result"))
                if isinstance(scorer_errors, dict)
                else "Scorer did not return a result"
            )
            return ScorerResult(status="error", error_code="missing_score", error_message=detail)
        value = case.scores[metric]
        return ScorerResult(status="skipped" if value is None else "ok", value=value)

    def _score(self, case: CaseResult, metric: str, item: EvaluationItem) -> EvaluationResult:
        outcome = self._outcome(case, metric)
        value = outcome.value
        kind = self.suite.scorer_kinds[metric]
        try:
            if outcome.status == "ok":
                if kind == "boolean":
                    if type(value) not in (bool, int, float) or value not in (0, 1):
                        raise ValueError
                    value = bool(value)
                elif kind == "numeric" and type(value) not in (int, float):
                    raise ValueError
                elif kind == "categorical" and not isinstance(value, list):
                    raise ValueError
            result = EvaluationResult(
                item=item,
                scorer_version_id=self.settings.scorer_versions[metric],
                value=value,
                status=outcome.status,
            )
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return EvaluationResult(
                item=item,
                scorer_version_id=self.settings.scorer_versions[metric],
                status="error",
                error_code="invalid_score",
                error_message="Scorer returned an unsupported value or status",
            )
        options: dict[str, object] = {"value": value, "status": outcome.status}
        omitted: dict[str, JSONValue] = {}
        for key, optional_value in {
            "reasoning": outcome.reasoning,
            "metadata": outcome.metadata,
            "error_code": outcome.error_code,
            "error_message": outcome.error_message[:16000].replace("\x00", "") if outcome.error_message else None,
            "evaluator_trace_id": outcome.evaluator_trace_id if self.application_trace_ids_enabled else None,
            "evaluated_at": outcome.evaluated_at,
        }.items():
            if optional_value is None:
                continue
            candidate = {**options, key: optional_value}
            try:
                result = EvaluationResult(
                    item=item,
                    scorer_version_id=self.settings.scorer_versions[metric],
                    **cast(ResultOptions, candidate),
                )
            except (ValueError, TypeError, UnicodeError, RecursionError):
                omitted[key] = "invalid or exceeds the offline result payload limit"
            else:
                options = candidate
        if not omitted:
            return result
        for field_name in ("metadata", "reasoning", "error_message", None):
            try:
                return EvaluationResult(
                    item=item,
                    scorer_version_id=self.settings.scorer_versions[metric],
                    **cast(
                        ResultOptions,
                        {
                            **options,
                            "metadata": {
                                **cast(dict[str, JSONValue], options.get("metadata", {})),
                                "omitted_fields": omitted,
                            },
                        },
                    ),
                )
            except ValueError:
                if field_name is None:
                    raise
                if field_name in options:
                    options.pop(field_name)
                    omitted[field_name] = "omitted to retain upload diagnostics within the payload limit"
        raise AssertionError("unreachable")

    def prepare(
        self,
        *,
        experiment_id: str,
        experiment_name: str,
        started_at: datetime,
        result: ExperimentResult,
        metadata: Mapping[str, object],
    ) -> OfflineEvalUpload:
        revision = metadata.get("git_sha")
        dataset: ExperimentOptions = {}
        if self.suite.experiment_options.get("dataset_revision_id") is None:
            dataset = {
                "dataset_source": "repository",
                "dataset_identifier": self.suite.key,
                "dataset_revision_identifier": revision if isinstance(revision, str) else None,
            }
        experiment: ExperimentOptions = {
            "run_source": "ci" if os.getenv("CI") else "local",
            "application_version": revision if isinstance(revision, str) else None,
            "model_version": str(metadata["agent_model"]) if metadata.get("agent_model") is not None else None,
            **dataset,
            **self.suite.experiment_options,
            "id": experiment_id,
            "started_at": started_at.isoformat(),
            "suite_key": self.suite.key,
            "expected_item_count": len(result.results),
            "expected_result_count": len(result.results) * len(self.suite.scorer_kinds),
        }
        experiment = cast(
            ExperimentOptions,
            {key: str(value) if isinstance(value, UUID) else value for key, value in experiment.items()},
        )
        trials: Counter[str] = Counter()
        items: list[EvaluationItem] = []
        scores: list[EvaluationResult] = []
        for index, case in enumerate(result.results):
            name = str(case.input.get("name", f"case-{index}"))
            trial = case.trial_index if case.trial_index is not None else trials[name]
            trials[name] += 1
            trace_id = case.metadata.get("trace_id")
            item = EvaluationItem(
                id=uuid5(UUID(experiment_id), json.dumps([name, trial])),
                case_key=name,
                trial=str(trial),
                application_trace_id=trace_id
                if self.application_trace_ids_enabled and isinstance(trace_id, str)
                else None,
                dataset_item_identifier=case.metadata.get("dataset_item_identifier"),
                dataset_item_version_identifier=case.metadata.get("dataset_item_version_identifier"),
                dataset_item_version_id=case.metadata.get("dataset_item_version_id"),
                payload=self._item_payload(
                    case, {**metadata, "braintrust_url": result.summary.experiment_url, "trial_index": trial}
                ),
            )
            items.append(item)
            scores.extend(self._score(case, metric, item) for metric in self.suite.scorer_kinds)
        return OfflineEvalUpload(
            host=self.settings.host,
            project_id=self.settings.project_id,
            experiment_name=experiment_name,
            experiment=experiment,
            items=tuple(items),
            results=tuple(scores),
        )

    async def publish(self, upload: OfflineEvalUpload) -> str:
        if upload.host != self.settings.host or upload.project_id != self.settings.project_id:
            raise OfflineUploadError("Saved upload destination differs from the configured host/project")
        try:
            async with AsyncOfflineEvaluations(
                host=self.settings.host,
                project_id=self.settings.project_id,
                secret_key=self.settings.api_key.get_secret_value(),
                timeout=self.settings.request_timeout,
                max_retries=self.settings.max_retries,
            ) as client:
                experiment = await client.create_experiment(name=upload.experiment_name, **upload.experiment)
                await experiment.upload_results(upload.results)
                await experiment.complete()
        except EvaluationAPIError as error:
            message = str(error)
            if error.status in (401, 403):
                message += " Check the key's offline_evaluation_ingestion:write scope and project access."
            raise OfflineUploadError(message) from None
        return (
            f"{upload.host}/project/{upload.project_id}"
            f"/ai-evals/evaluations/offline/experiments/{upload.experiment['id']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry a saved offline upload without rerunning agents or scorers")
    parser.add_argument("upload", type=Path)
    args = parser.parse_args()
    try:
        settings = OfflineEvalSettings.from_env()
        if settings is None:
            raise OfflineUploadError("Set POSTHOG_OFFLINE_EVAL_API_KEY and POSTHOG_OFFLINE_EVAL_PROJECT_ID")
        upload = OfflineEvalUpload.load(args.upload)
        publisher = OfflineEvalPublisher(settings, OfflineEvalSuite(key="replay", scorer_kinds={}))
        url = asyncio.run(publisher.publish(upload))
    except (OfflineUploadError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Offline upload failed: {error}\n")
    parser.exit(0, f"PostHog: {url}\n")


if __name__ == "__main__":
    main()
