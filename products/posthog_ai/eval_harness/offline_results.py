from __future__ import annotations

import os
import re
import json
import asyncio
import logging
from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from posthoganalytics.ai.evaluations import (
    AsyncOfflineEvaluations,
    BulkUploadError,
    EvaluationAPIError,
    EvaluationItem,
    EvaluationResult,
    ExperimentOptions,
    JSONValue,
    ResultOptions,
    ScorerKind,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from posthog.dataclasses import frozen

from .engines.types import CaseResult, ExperimentResult, ScorerResult

logger = logging.getLogger(__name__)
TAG_TIMEOUT_SECONDS = 5.0
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@frozen
class OfflineScorer:
    kind: ScorerKind
    version: UUID


@frozen
class OfflineEvalSuite:
    key: str
    project_id: int
    scorer_kinds: Mapping[str, ScorerKind]
    scorer_versions: Mapping[str, UUID]
    tags: tuple[str, ...] = ()
    experiment_options: ExperimentOptions = field(default_factory=lambda: ExperimentOptions())

    @classmethod
    def from_scorers(
        cls, *, key: str, project_id: int, scorers: Mapping[str, OfflineScorer], tags: tuple[str, ...]
    ) -> OfflineEvalSuite:
        return cls(
            key=key,
            project_id=project_id,
            scorer_kinds={metric: scorer.kind for metric, scorer in scorers.items()},
            scorer_versions={metric: scorer.version for metric, scorer in scorers.items()},
            tags=tags,
        )


class OfflineUploadError(Exception):
    @staticmethod
    def _safe_token(value: object, *, path: bool) -> str | None:
        pattern = (
            r"[a-z][a-z0-9_]{0,63}(?:\.(?:[a-z][a-z0-9_]{0,63}|[0-9]{1,6})){0,5}" if path else r"[a-z][a-z0-9_]{0,63}"
        )
        return value if isinstance(value, str) and len(value) <= 128 and re.fullmatch(pattern, value) else None

    def __init__(self, message: str, *, api_error: EvaluationAPIError | None = None) -> None:
        self.status = api_error.status if api_error is not None else None
        self.code = self._safe_token(api_error.code, path=False) if api_error is not None else None
        self.attr = self._safe_token(api_error.attr, path=True) if api_error is not None else None
        self.persistence = api_error.persistence if api_error is not None else None
        self.retry_after = api_error.retry_after if api_error is not None else None
        self.completed_chunk_count: int | None = None
        self.acknowledged_item_count: int | None = None
        self.acknowledged_result_count: int | None = None
        self.pending_result_count: int | None = None
        self.failed_index: int | None = None
        details: list[str] = []
        if self.code is not None:
            details.append(f"code={self.code}")
        if self.attr is not None:
            details.append(f"field={self.attr}")
        if self.persistence is not None:
            details.append(f"persistence={self.persistence}")
        if self.retry_after is not None:
            details.append(f"retry after {self.retry_after:g}s")
        if isinstance(api_error, BulkUploadError):
            chunks = api_error.completed.chunks
            self.completed_chunk_count = len(chunks)
            self.acknowledged_item_count = len({item.id for chunk in chunks for item in chunk.items})
            self.acknowledged_result_count = len({result.id for chunk in chunks for result in chunk.results})
            self.pending_result_count = len(api_error.pending_results)
            self.failed_index = api_error.failed_index
            details.append(
                f"acknowledged {self.acknowledged_item_count} items and {self.acknowledged_result_count} results "
                f"in {self.completed_chunk_count} batches; {self.pending_result_count} results await acknowledgment"
            )
        if details:
            message += " " + "; ".join(details) + "."
        if self.status in (401, 403):
            message += " Check the key's offline_evaluation_ingestion:write scope and project access."
        super().__init__(message)


class LocalOfflineEvalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    project_id: int = Field(gt=0)
    scorer_versions: dict[UUID, UUID]

    @classmethod
    def load(cls, path: str) -> LocalOfflineEvalConfig:
        try:
            return cls.model_validate_json(Path(path).read_text())
        except (OSError, UnicodeError, ValidationError):
            raise OfflineUploadError(
                "POSTHOG_OFFLINE_EVAL_LOCAL_CONFIG must point to a valid local destination JSON"
            ) from None

    def remap_scorers(self, suite: OfflineEvalSuite) -> dict[str, UUID]:
        try:
            return {metric: self.scorer_versions[suite.scorer_versions[metric]] for metric in suite.scorer_kinds}
        except KeyError:
            raise OfflineUploadError(
                f"Local offline evaluation config must map every enrolled scorer version for {suite.key}"
            ) from None


class OfflineEvalSettings(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    host: str = "https://us.posthog.com"
    project_id: int = Field(gt=0)
    api_key: SecretStr
    scorer_versions: dict[str, UUID]
    request_timeout: float = Field(default=5, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, api_key: SecretStr) -> SecretStr:
        value = api_key.get_secret_value()
        if not value or any(character.isspace() for character in value):
            raise OfflineUploadError("POSTHOG_OFFLINE_EVAL_API_KEY must be nonempty and contain no whitespace")
        return api_key

    @field_validator("host")
    @classmethod
    def normalize_host(cls, host: str) -> str:
        error = "POSTHOG_OFFLINE_EVAL_HOST must be an HTTPS origin or HTTP loopback origin"
        try:
            parsed = urlsplit(host.strip().rstrip("/"))
            port = parsed.port
        except ValueError:
            raise OfflineUploadError(error) from None
        if (
            not (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS))
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise OfflineUploadError(error)
        origin = parsed.netloc.lower()
        if parsed.scheme == "https" and port in (None, 443):
            origin = {
                "app.posthog.com": "us.posthog.com",
                "us.i.posthog.com": "us.posthog.com",
                "eu.i.posthog.com": "eu.posthog.com",
            }.get(parsed.hostname, origin.removesuffix(":443"))
        return f"{parsed.scheme}://{origin}"

    @classmethod
    def from_env(cls, suite: OfflineEvalSuite) -> OfflineEvalSettings | None:
        prefix = "POSTHOG_OFFLINE_EVAL_"
        api_key = os.getenv(prefix + "API_KEY")
        if not api_key:
            return None
        host = cls.normalize_host(os.getenv(prefix + "HOST", "https://us.posthog.com"))
        local_config = None
        if local_config_path := os.getenv(prefix + "LOCAL_CONFIG"):
            if urlsplit(host).hostname not in LOOPBACK_HOSTS:
                raise OfflineUploadError("POSTHOG_OFFLINE_EVAL_LOCAL_CONFIG requires a loopback upload host")
            local_config = LocalOfflineEvalConfig.load(local_config_path)
        try:
            settings = cls(
                host=host,
                project_id=local_config.project_id if local_config is not None else suite.project_id,
                api_key=SecretStr(api_key),
                scorer_versions=local_config.remap_scorers(suite)
                if local_config is not None
                else dict(suite.scorer_versions),
            )
        except ValidationError:
            raise OfflineUploadError(
                "Offline evaluation suite has an invalid project ID or scorer version mapping"
            ) from None
        if not set(suite.scorer_kinds) <= set(settings.scorer_versions):
            raise OfflineUploadError("Offline evaluation suite must map every enrolled metric to a scorer version UUID")
        enrolled_versions = [settings.scorer_versions[metric] for metric in suite.scorer_kinds]
        if len(set(enrolled_versions)) != len(enrolled_versions):
            raise OfflineUploadError("Each offline metric must have a distinct scorer version UUID")
        return settings


@frozen
class OfflineEvalUpload:
    host: str
    project_id: int
    experiment_name: str
    experiment: ExperimentOptions
    results: tuple[EvaluationResult, ...]
    tags: tuple[str, ...] = ()


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
        self._attempted_tag_updates: set[str] = set()

    def _item_payload(
        self,
        case: CaseResult,
        metadata: Mapping[str, object],
        omitted: list[str],
    ) -> dict[str, JSONValue]:
        output = case.output
        if isinstance(output, dict) and "raw_log" in output:
            output = {key: value for key, value in output.items() if key != "raw_log"}
            omitted.append("output.raw_log")
        fields = {
            "input": case.input,
            "output": output,
            "expected_output": case.expected,
            "metadata": {**metadata, "case": case.metadata},
        }
        # Reserve fixed omission markers so diagnostics never displace accepted fields.
        reserved: dict[str, JSONValue] = {"omitted_fields": [*omitted, *fields]}
        payload: dict[str, JSONValue] = {"metadata": reserved}
        for key, value in fields.items():
            candidate = {**payload, key: cast(JSONValue, value)}
            if key == "metadata":
                candidate[key] = {**cast(dict[str, JSONValue], value), **reserved}
            try:
                EvaluationItem(payload=candidate)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                omitted.append(key)
            else:
                payload = candidate
        payload["metadata"] = {**cast(dict[str, JSONValue], payload["metadata"]), "omitted_fields": [*omitted]}
        return payload

    def _item(
        self,
        case: CaseResult,
        *,
        item_id: UUID,
        name: str,
        trial: int,
        metadata: Mapping[str, object],
    ) -> EvaluationItem:
        declaration: dict[str, object] = {"id": str(item_id), "trial": str(trial)}
        omitted: list[str] = []
        for key, value in {
            "case_key": name,
            "application_trace_id": case.metadata.get("trace_id") if self.application_trace_ids_enabled else None,
            "dataset_item_identifier": case.metadata.get("dataset_item_identifier"),
            "dataset_item_version_identifier": case.metadata.get("dataset_item_version_identifier"),
        }.items():
            if value is None:
                continue
            candidate = {**declaration, key: value}
            try:
                EvaluationItem.from_dict(candidate)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                omitted.append(key)
            else:
                declaration = candidate
        return EvaluationItem.from_dict({**declaration, "payload": self._item_payload(case, metadata, omitted)})

    def _outcome(self, case: CaseResult, metric: str) -> ScorerResult:
        if case.error is not None and case.error_kind == "task":
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
            EvaluationResult(
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
        fields = {
            "reasoning": outcome.reasoning,
            "metadata": outcome.metadata,
            "error_code": outcome.error_code,
            "error_message": outcome.error_message,
            "evaluator_trace_id": outcome.evaluator_trace_id if self.application_trace_ids_enabled else None,
            "evaluated_at": outcome.evaluated_at,
        }
        omitted: list[str] = []
        for key, optional_value in fields.items():
            if optional_value is None:
                continue
            candidate = {**options, key: optional_value}
            try:
                EvaluationResult(
                    item=item,
                    scorer_version_id=self.settings.scorer_versions[metric],
                    **cast(
                        ResultOptions,
                        {
                            **candidate,
                            "metadata": {
                                **cast(dict[str, JSONValue], candidate.get("metadata", {})),
                                "omitted_fields": list(fields),
                            },
                        },
                    ),
                )
            except (ValueError, TypeError, UnicodeError, RecursionError):
                omitted.append(key)
            else:
                options = candidate
        if omitted:
            options["metadata"] = {
                **cast(dict[str, JSONValue], options.get("metadata", {})),
                "omitted_fields": omitted,
            }
        return EvaluationResult(
            item=item,
            scorer_version_id=self.settings.scorer_versions[metric],
            **cast(ResultOptions, options),
        )

    def prepare(
        self,
        *,
        experiment_id: str,
        experiment_name: str,
        started_at: datetime,
        result: ExperimentResult,
        metadata: Mapping[str, object],
    ) -> OfflineEvalUpload:
        if not self.suite.scorer_kinds:
            raise OfflineUploadError("An offline evaluation suite must enroll at least one scorer")
        if self.suite.experiment_options.get("dataset_revision_id") is not None:
            raise OfflineUploadError("Hosted datasets are not supported by the harness publisher")
        revision = metadata.get("git_sha")
        experiment: ExperimentOptions = {
            "run_source": "ci" if os.getenv("CI") else "local",
            "application_version": revision if isinstance(revision, str) else None,
            "model_version": str(metadata["agent_model"]) if metadata.get("agent_model") is not None else None,
            "dataset_source": "repository",
            "dataset_identifier": self.suite.key,
            "dataset_revision_identifier": revision if isinstance(revision, str) else None,
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
        scores: list[EvaluationResult] = []
        for index, case in enumerate(result.results):
            name = str(case.input.get("name", f"case-{index}"))
            trial = case.trial_index if case.trial_index is not None else trials[name]
            trials[name] += 1
            item = self._item(
                case,
                item_id=uuid5(UUID(experiment_id), json.dumps([name, trial])),
                name=name,
                trial=trial,
                metadata={**metadata, "braintrust_url": result.summary.experiment_url, "trial_index": trial},
            )
            scores.extend(self._score(case, metric, item) for metric in self.suite.scorer_kinds)
        return OfflineEvalUpload(
            host=self.settings.host,
            project_id=self.settings.project_id,
            experiment_name=experiment_name,
            experiment=experiment,
            results=tuple(scores),
            tags=self.suite.tags,
        )

    def _client(self) -> AsyncOfflineEvaluations:
        return AsyncOfflineEvaluations(
            host=self.settings.host,
            project_id=self.settings.project_id,
            secret_key=self.settings.api_key.get_secret_value(),
            timeout=self.settings.request_timeout,
            max_retries=self.settings.max_retries,
        )

    async def tag(self, upload: OfflineEvalUpload) -> None:
        if upload.host != self.settings.host or upload.project_id != self.settings.project_id:
            raise OfflineUploadError("Upload destination differs from the configured host/project")
        experiment_id = str(upload.experiment["id"])
        if not upload.tags or experiment_id in self._attempted_tag_updates:
            return
        self._attempted_tag_updates.add(experiment_id)
        try:
            async with asyncio.timeout(TAG_TIMEOUT_SECONDS), self._client() as client:
                await client.resume_experiment(experiment_id).set_tags(upload.tags)
        except EvaluationAPIError as error:
            logger.warning(
                "PostHog offline results uploaded, but tagging failed for experiment %s (status=%s, code=%s). "
                "Tagging requires a personal key with evaluation:write. Tag updates are not retried.",
                experiment_id,
                error.status,
                OfflineUploadError._safe_token(error.code, path=False),
            )
        except TimeoutError:
            logger.warning(
                "PostHog offline results uploaded, but tagging timed out for experiment %s. "
                "Tag updates are not retried.",
                experiment_id,
            )
        except asyncio.CancelledError:
            logger.warning(
                "PostHog offline tag update interrupted for experiment %s; inspect its tags before retrying.",
                experiment_id,
            )
            raise

    async def publish(self, upload: OfflineEvalUpload) -> str:
        if upload.host != self.settings.host or upload.project_id != self.settings.project_id:
            raise OfflineUploadError("Upload destination differs from the configured host/project")
        try:
            async with self._client() as client:
                experiment = await client.create_experiment(name=upload.experiment_name, **upload.experiment)
                try:
                    await experiment.upload_results(upload.results)
                    await experiment.complete()
                except EvaluationAPIError:
                    with suppress(Exception):
                        await asyncio.wait_for(experiment.fail(), timeout=5)
                    raise
        except EvaluationAPIError as error:
            raise OfflineUploadError(str(error), api_error=error) from None
        return (
            f"{upload.host}/project/{upload.project_id}"
            f"/ai-evals/evaluations/offline/experiments/{upload.experiment['id']}"
        )
