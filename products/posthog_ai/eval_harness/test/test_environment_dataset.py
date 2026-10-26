from __future__ import annotations

import os
import sys
import json
import hashlib
import tempfile
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from unittest import TestCase

import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized

from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset
from products.posthog_ai.eval_harness.environment.schema import (
    EVENT_TABLE,
    METRIC_TABLE,
    EnvironmentEvent,
    EnvironmentMetric,
)
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform

SOURCE = datetime(2032, 4, 6, 12, 0, 0, 123456, tzinfo=UTC)


def event(identifier: UUID | None = None) -> EnvironmentEvent:
    return EnvironmentEvent(
        uuid=identifier or uuid4(),
        timestamp=SOURCE - timedelta(hours=2),
        event="parcel_scanned",
        distinct_id="00123",
        person_id=uuid4(),
        properties={"attempts": 2, "delivered": False, "items": [0, "0", None], "nested": {"empty": ""}},
        created_at=SOURCE - timedelta(hours=1),
    )


def metric() -> EnvironmentMetric:
    return EnvironmentMetric(
        id=uuid4(),
        created_at=SOURCE - timedelta(days=1),
        name="parcels_total",
        description="Count invented parcel scans.",
        definition={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
        referenced_table_names=["events"],
        status="approved",
        approved_at=SOURCE - timedelta(hours=1),
    )


class TestEnvironmentDataset(TestCase):
    @parameterized.expand([0, 1, 5001])
    def test_build_retains_typed_rows_and_deduplicates_overlapping_parts(self, count: int) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = event()
            rows = [original.model_copy(update={"uuid": uuid4()}) for _ in range(count)]
            part = root / "input.parquet"
            EVENT_TABLE.write(part, rows)
            source_hash = hashlib.sha256(part.read_bytes()).hexdigest()
            definition = metric()
            metrics = root / "metrics.parquet"
            METRIC_TABLE.write(metrics, [definition])
            prepared = EnvironmentDataset.build(
                root / "bundle",
                environment_id="parcel_fixture",
                event_paths=[part, part],
                metrics_path=metrics,
                source_cutoff=SOURCE,
                timezone="Asia/Kolkata",
            )
            loaded = EnvironmentDataset.load(prepared.path)
            self.assertEqual(loaded.manifest, prepared.manifest)
            self.assertEqual(loaded.manifest.event_count, count)
            self.assertEqual(loaded.manifest.metric_count, 1)
            self.assertEqual(loaded.manifest.checkpoint, SOURCE)
            self.assertEqual(loaded.manifest.timezone, "Asia/Kolkata")
            self.assertEqual(list(loaded.events()), rows)
            self.assertEqual(loaded.metrics, [definition])
            self.assertEqual(hashlib.sha256(part.read_bytes()).hexdigest(), source_hash)
            self.assertEqual(loaded.path.parent.stat().st_mode & 0o777, 0o700)
            for file in loaded.path.parent.iterdir():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            loaded.validate_files()
            with self.assertRaisesRegex(ValueError, "new or empty"):
                EnvironmentDataset.build(
                    root / "bundle", environment_id="parcel_fixture", event_paths=[part], source_cutoff=SOURCE
                )

    @parameterized.expand(["uuid_conflict", "timestamp", "created_at", "integer", "schema"])
    def test_invalid_event_parts_never_publish_a_manifest(self, invalid: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = event()
            last = event()
            if invalid == "uuid_conflict":
                last = first.model_copy(update={"event": "different_event"})
            elif invalid in {"timestamp", "created_at"}:
                last = last.model_copy(update={invalid: SOURCE})
            elif invalid == "integer":
                last = last.model_copy(update={"properties": {"nested": [{"too_large": 2**80}]}})
            part = root / "events.parquet"
            EVENT_TABLE.write(part, [first, last])
            if invalid == "schema":
                table = pq.read_table(part).append_column("unexpected", pa.array(["a", "b"]))
                pq.write_table(table, part)
            with self.assertRaises(ValueError):
                EnvironmentDataset.build(
                    root / "bundle", environment_id="parcel_fixture", event_paths=[part], source_cutoff=SOURCE
                )
            self.assertFalse((root / "bundle" / "environment.json").exists())

    @parameterized.expand(["id", "name", "table", "created_at", "approved_at", "integer"])
    def test_invalid_metrics_are_rejected_before_packaging(self, invalid: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = metric()
            last = first.model_copy(update={"id": uuid4(), "name": "another_metric"})
            if invalid == "id":
                last = first
            elif invalid == "name":
                last = last.model_copy(update={"name": first.name})
            elif invalid == "table":
                last = last.model_copy(update={"referenced_table_names": ["missing_warehouse_table"]})
            elif invalid in {"created_at", "approved_at"}:
                last = last.model_copy(update={invalid: SOURCE + timedelta(seconds=1)})
            elif invalid == "integer":
                last = last.model_copy(update={"definition": {"nested": {"value": -(2**80)}}})
            part = root / "metrics.parquet"
            METRIC_TABLE.write(part, [first, last])
            with self.assertRaises(ValueError):
                EnvironmentDataset.build(
                    root / "bundle",
                    environment_id="parcel_fixture",
                    event_paths=[],
                    metrics_path=part,
                    source_cutoff=SOURCE,
                )
            self.assertFalse((root / "bundle").exists())

    @parameterized.expand(["hash", "escape", "count", "metric_count", "checkpoint", "timezone", "duplicate"])
    def test_load_rejects_changed_or_inconsistent_bundles(self, changed: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            part = root / "events.parquet"
            original = event()
            EVENT_TABLE.write(part, [original])
            dataset = EnvironmentDataset.build(
                root / "bundle", environment_id="parcel_fixture", event_paths=[part], source_cutoff=SOURCE
            )
            manifest = json.loads(dataset.path.read_bytes())
            if changed == "hash":
                manifest["events"][0]["sha256"] = "0" * 64
            elif changed == "escape":
                manifest["events"][0]["path"] = "../events.parquet"
            elif changed == "count":
                manifest["event_count"] = 0
            elif changed == "metric_count":
                manifest["metric_count"] = 1
            elif changed == "checkpoint":
                manifest["checkpoint"] = (SOURCE + timedelta(seconds=1)).isoformat()
            elif changed == "timezone":
                manifest["timezone"] = "not_a_timezone"
            else:
                duplicate_path = dataset.path.parent / "events.parquet"
                EVENT_TABLE.write(duplicate_path, [original, original])
                manifest["events"][0]["sha256"] = hashlib.sha256(duplicate_path.read_bytes()).hexdigest()
                manifest["event_count"] = 2
            dataset.path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                EnvironmentDataset.load(dataset.path)
            with self.assertRaises(ValueError):
                dataset.validate_files()

    def test_rehash_detects_changed_data_before_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = EnvironmentDataset.build(
                root / "bundle", environment_id="empty_fixture", event_paths=[], source_cutoff=SOURCE
            )
            EVENT_TABLE.write(dataset.path.parent / "events.parquet", [event()])
            with self.assertRaisesRegex(ValueError, "checksum"):
                dataset.validate_files()

    def test_import_does_not_initialize_django_or_product_runtimes(self) -> None:
        environment = dict(os.environ)
        environment.pop("DJANGO_SETTINGS_MODULE", None)
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import products.posthog_ai.eval_harness.environment.dataset; "
                "from django.conf import settings; assert not settings.configured; "
                "assert not any(name.startswith(('products.signals.', 'products.tasks.')) for name in sys.modules)",
            ],
            cwd=Path(__file__).resolve().parents[4],
            env=environment,
            check=True,
            capture_output=True,
        )


class TestEnvironmentTransform(TestCase):
    def test_rejects_colliding_nested_keys_without_changing_source(self) -> None:
        transform = EnvironmentTransform(
            source_cutoff=SOURCE,
            target_cutoff=SOURCE,
            record_ids=[],
            string_replacements={"prior_field": "current_field"},
        )
        source = {"properties": {"prior_field": 1, "current_field": 2}}
        with self.assertRaisesRegex(ValueError, "key collision"):
            transform.value(source)
        self.assertEqual(source, {"properties": {"prior_field": 1, "current_field": 2}})

    def test_shift_preserves_literal_precision_and_record_identity_relationships(self) -> None:
        identifier, namespace, external = uuid4(), uuid4(), uuid4()
        transform = EnvironmentTransform(
            source_cutoff=SOURCE,
            target_cutoff=SOURCE + timedelta(days=3),
            namespace=namespace,
            record_ids=[identifier],
            time_strings=["2032-04-05", "2032-04-05T01:02:03.120Z"],
            string_replacements={"warehouse-old": "warehouse-local"},
        )
        alias = uuid5(namespace, str(identifier))
        self.assertEqual(transform.identity(identifier), alias)
        self.assertEqual(transform.delta, timedelta(days=3))
        self.assertEqual(
            transform.value(
                {
                    "metric": str(identifier),
                    "external": str(external),
                    "time": SOURCE,
                    "types": [True, 0, "0", None],
                    "query": "2032-04-05 2032-04-05T01:02:03.120Z warehouse-old",
                    "archive": "path/2032-04-05/file 2032-04-05T12:34:56Z",
                }
            ),
            {
                "metric": str(alias),
                "external": str(external),
                "time": SOURCE + timedelta(days=3),
                "types": [True, 0, "0", None],
                "query": "2032-04-08 2032-04-08T01:02:03.120Z warehouse-local",
                "archive": "path/2032-04-05/file 2032-04-05T12:34:56Z",
            },
        )
        same = EnvironmentTransform(
            source_cutoff=SOURCE, target_cutoff=SOURCE, namespace=namespace, record_ids=[identifier]
        )
        self.assertEqual(same.identity(identifier), alias)

    @parameterized.expand(["naive", "date", "empty", "duplicate", "overlap"])
    def test_invalid_shift_policy_is_rejected(self, invalid: str) -> None:
        identifier = uuid4()
        with self.assertRaises(ValueError):
            EnvironmentTransform(
                source_cutoff=SOURCE,
                target_cutoff=SOURCE.replace(tzinfo=None) if invalid == "naive" else SOURCE,
                record_ids=[identifier, identifier] if invalid == "duplicate" else [identifier],
                time_strings={"date": ["2032-99-99"], "overlap": ["2032-04-01"]}.get(invalid, []),
                string_replacements={"empty": {"": "x"}, "overlap": {"2032-04-01": "2032-04-02"}}.get(invalid, {}),
            )
