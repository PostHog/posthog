from __future__ import annotations

import os
import json
import hashlib
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from uuid import UUID

from products.posthog_ai.eval_harness.environment.schema import (
    EVENT_TABLE,
    METRIC_TABLE,
    EnvironmentEvent,
    EnvironmentFile,
    EnvironmentManifest,
    EnvironmentMetric,
)
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform


def validate_json_numbers(value: object) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int) and not -(2**63) <= value <= 2**64 - 1:
        raise ValueError("Environment JSON integers must fit ClickHouse JSON without rounding.")
    if isinstance(value, Mapping):
        for item in value.values():
            validate_json_numbers(item)
    elif isinstance(value, list):
        for item in value:
            validate_json_numbers(item)


class EnvironmentDataset:
    def __init__(
        self,
        path: Path,
        manifest: EnvironmentManifest,
        manifest_sha256: str,
        metrics: Sequence[EnvironmentMetric],
    ) -> None:
        self.path = path
        self.manifest = manifest
        self.manifest_sha256 = manifest_sha256
        self._metrics = tuple(metrics)

    @property
    def metrics(self) -> list[EnvironmentMetric]:
        return list(self._metrics)

    @staticmethod
    def _validate_scout(path: Path, manifest: EnvironmentManifest) -> None:
        from products.signals.backend.facade.eval_environment import (  # noqa: PLC0415 — Scout schemas are optional for event-only bundles
            validate_scout_bundle,
        )

        validate_scout_bundle(path, manifest)

    def validate_files(self) -> None:
        content = self.path.read_bytes()
        if (
            hashlib.sha256(content).hexdigest() != self.manifest_sha256
            or EnvironmentManifest.model_validate_json(content) != self.manifest
        ):
            raise ValueError("The environment manifest changed after validation.")
        for reference in self.manifest.events:
            reference.resolve(self.path.parent)
        if self.manifest.metrics:
            self.manifest.metrics.resolve(self.path.parent)
        if self.manifest.scout:
            self._validate_scout(self.manifest.scout.resolve(self.path.parent), self.manifest)

    def events(self) -> Iterator[EnvironmentEvent]:
        for reference in self.manifest.events:
            yield from EVENT_TABLE.read(reference.resolve(self.path.parent))

    @staticmethod
    def _validate_event(event: EnvironmentEvent, source_cutoff: datetime) -> None:
        if event.timestamp >= source_cutoff or event.created_at >= source_cutoff:
            raise ValueError("An environment event is at or after the exclusive source cutoff.")
        validate_json_numbers(event.properties)

    @staticmethod
    def _validate_metrics(metrics: Sequence[EnvironmentMetric], checkpoint: datetime) -> None:
        identifiers: set[UUID] = set()
        live_names: set[str] = set()
        for metric in metrics:
            if metric.id in identifiers:
                raise ValueError("Environment metrics contain duplicate record IDs.")
            identifiers.add(metric.id)
            if metric.deleted is False:
                if metric.name in live_names:
                    raise ValueError("Environment metrics contain duplicate live names.")
                live_names.add(metric.name)
            unsupported_tables = set(metric.referenced_table_names) - {"events"}
            if unsupported_tables:
                raise ValueError(
                    "Environment metrics reference unsupported tables: " + ", ".join(sorted(unsupported_tables))
                )
            for value in metric.model_dump().values():
                if isinstance(value, datetime) and value > checkpoint:
                    raise ValueError("An environment metric timestamp is after the source checkpoint.")
            validate_json_numbers(metric.definition)

    @staticmethod
    def _validate_policy(manifest: EnvironmentManifest, metrics: Sequence[EnvironmentMetric]) -> None:
        EnvironmentTransform(
            source_cutoff=manifest.source_cutoff,
            target_cutoff=manifest.source_cutoff,
            record_ids=[metric.id for metric in metrics],
            time_strings=manifest.time_strings,
            string_replacements=manifest.string_replacements,
            source_project_url=manifest.source_project_url,
        )

    @classmethod
    def load(cls, path: Path) -> EnvironmentDataset:
        path = path.resolve(strict=True)
        content = path.read_bytes()
        manifest = EnvironmentManifest.model_validate_json(content)
        if manifest.scout:
            cls._validate_scout(manifest.scout.resolve(path.parent), manifest)
        metrics = list(METRIC_TABLE.read(manifest.metrics.resolve(path.parent))) if manifest.metrics else []
        if len(metrics) != manifest.metric_count:
            raise ValueError("The environment metric count does not match its manifest.")
        cls._validate_metrics(metrics, manifest.checkpoint)
        cls._validate_policy(manifest, metrics)
        dataset = cls(path, manifest, hashlib.sha256(content).hexdigest(), metrics)
        identifiers: set[UUID] = set()
        count = 0
        for event in dataset.events():
            cls._validate_event(event, manifest.source_cutoff)
            if event.uuid in identifiers:
                raise ValueError("The prepared environment contains duplicate event UUIDs.")
            identifiers.add(event.uuid)
            count += 1
        if count != manifest.event_count:
            raise ValueError("The environment event count does not match its manifest.")
        return dataset

    @staticmethod
    def _reference(path: Path, directory: Path) -> EnvironmentFile:
        path.chmod(0o600)
        with path.open("rb") as content:
            digest = hashlib.file_digest(content, "sha256").hexdigest()
        return EnvironmentFile(path=path.relative_to(directory).as_posix(), sha256=digest)

    @classmethod
    def build(
        cls,
        output: Path,
        *,
        environment_id: str,
        event_paths: Sequence[Path],
        metrics_path: Path | None = None,
        scout_case_path: Path | None = None,
        source_cutoff: datetime,
        timezone: str = "UTC",
        time_strings: Sequence[str] = (),
        string_replacements: Mapping[str, str] | None = None,
        source_project_url: str | None = None,
    ) -> EnvironmentDataset:
        manifest = EnvironmentManifest(
            environment_id=environment_id,
            source_cutoff=source_cutoff,
            checkpoint=source_cutoff,
            timezone=timezone,
            time_strings=list(time_strings),
            string_replacements=dict(string_replacements or {}),
            source_project_url=source_project_url,
            event_count=0,
            metric_count=0,
        )
        metrics = list(METRIC_TABLE.read(metrics_path)) if metrics_path else []
        cls._validate_metrics(metrics, source_cutoff)
        cls._validate_policy(manifest, metrics)
        if scout_case_path is not None:
            cls._validate_scout(scout_case_path, manifest)
        if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
            raise ValueError("Build requires a new or empty environment directory.")
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        output = output.resolve()
        output.chmod(0o700)
        seen: dict[UUID, bytes] = {}

        def events() -> Iterator[EnvironmentEvent]:
            for path in event_paths:
                for event in EVENT_TABLE.read(path):
                    cls._validate_event(event, source_cutoff)
                    encoded = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                    digest = hashlib.sha256(encoded.encode()).digest()
                    previous = seen.get(event.uuid)
                    if previous is not None:
                        if previous != digest:
                            raise ValueError("Environment input parts contain conflicting event UUIDs.")
                        continue
                    seen[event.uuid] = digest
                    yield event

        event_path = output / "events.parquet"
        event_path.touch(mode=0o600, exist_ok=False)
        EVENT_TABLE.write(event_path, events())
        metric_file = None
        if metrics_path is not None:
            metric_path = output / "metrics.parquet"
            metric_path.touch(mode=0o600, exist_ok=False)
            METRIC_TABLE.write(metric_path, metrics)
            metric_file = cls._reference(metric_path, output)
        scout_file = None
        if scout_case_path is not None:
            scout_path = output / "scout.json"
            descriptor = os.open(scout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as document:
                document.write(scout_case_path.read_bytes())
            cls._validate_scout(scout_path, manifest)
            scout_file = cls._reference(scout_path, output)
        manifest = manifest.model_copy(
            update={
                "schema_version": 2 if scout_file else 1,
                "events": [cls._reference(event_path, output)],
                "metrics": metric_file,
                "scout": scout_file,
                "event_count": len(seen),
                "metric_count": len(metrics),
            }
        )
        path = output / "environment.json"
        content = (
            manifest.model_dump_json(indent=2, exclude={"scout"} if scout_file is None else set()) + "\n"
        ).encode()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as document:
            document.write(content)
        return cls(path, manifest, hashlib.sha256(content).hexdigest(), metrics)
