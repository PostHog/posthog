from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models import EventDefinition, Organization, PropertyDefinition, Team, User
from posthog.models.event.new_events_schema import use_new_events_schema

from products.cdp.backend.facade.models import HogFunction
from products.data_catalog.backend.facade.api import Metric
from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset
from products.posthog_ai.eval_harness.environment.events import EnvironmentEvents
from products.posthog_ai.eval_harness.environment.guard import EnvironmentMigrationsPending
from products.posthog_ai.eval_harness.environment.restore import PreparedEnvironment
from products.posthog_ai.eval_harness.environment.schema import (
    EVENT_TABLE,
    METRIC_TABLE,
    EnvironmentEvent,
    EnvironmentMetric,
)

from common.hogvm.python.execute import execute_bytecode

SOURCE = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def make_environment(
    directory: Path,
    *,
    events: Sequence[EnvironmentEvent] = (),
    metrics: Sequence[EnvironmentMetric] = (),
    timezone: str = "UTC",
) -> EnvironmentDataset:
    directory.mkdir(parents=True, exist_ok=True)
    event_path = directory / "source-events.parquet"
    EVENT_TABLE.write(event_path, events)
    metric_path = directory / "source-metrics.parquet"
    METRIC_TABLE.write(metric_path, metrics)
    return EnvironmentDataset.build(
        directory / "bundle",
        environment_id="delivery-example",
        event_paths=[event_path],
        metrics_path=metric_path,
        source_cutoff=SOURCE,
        timezone=timezone,
    )


class TestEnvironmentRestoreValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ({"DEBUG": False},),
            ({"CLOUD_DEPLOYMENT": "US"},),
            ({"CLICKHOUSE_HOST": "warehouse.example.com"},),
            ({"CLICKHOUSE_STABLE_HOST": "warehouse.example.com"},),
            ({"DATABASES": {"default": {"HOST": "database.example.com", "NAME": "posthog"}}},),
        ]
    )
    def test_refuses_nonlocal_databases_before_import(self, changed: dict[str, object]) -> None:
        with override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None), override_settings(**changed):
            for preflight in (PreparedEnvironment.assert_local, PreparedEnvironment.assert_migrations_current):
                with self.assertRaisesRegex(RuntimeError, "require"):
                    preflight()

    @parameterized.expand(["function", "columns"])
    def test_refuses_outdated_native_clickhouse_before_import(self, missing: str) -> None:
        def schema_query(query: str, params: dict[str, object]) -> list[tuple[str]]:
            if "system.tables" in query:
                tables = params["tables"]
                assert isinstance(tables, tuple)
                return [(name,) for name in tables]
            if "system.functions" in query:
                available = {"JSONCleanPostHogEventProperties", "JSONCleanPostHogTemporaryProperties"}
                if missing != "function":
                    available.add("JSONCleanPostHogEvent")
                functions = params["functions"]
                assert isinstance(functions, tuple)
                return [(name,) for name in functions if name in available]
            if "system.columns" in query:
                return [("properties_null_keys",)]
            raise AssertionError("Preflight must only inspect the ClickHouse schema")

        with (
            override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None),
            patch("products.posthog_ai.eval_harness.environment.events.use_new_events_schema", return_value=True),
            patch("products.posthog_ai.eval_harness.environment.events.sync_execute", side_effect=schema_query),
            self.assertRaisesRegex(RuntimeError, f"native JSON .*{missing}.*not ready"),
        ):
            EnvironmentEvents.preflight()

    @parameterized.expand(["default", "product"])
    def test_pending_migrations_refuse_restore_without_creating_import_state(self, database: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = make_environment(root / "source")
            workspace = root / "import"
            with (
                override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None),
                patch(
                    "products.posthog_ai.eval_harness.environment.restore.get_pending_postgres_migrations",
                    return_value=["posthog.0001_initial"] if database == "default" else [],
                ),
                patch(
                    "products.posthog_ai.eval_harness.environment.restore.collect_unapplied_product_migrations",
                    return_value={"product_db_writer": ["product.0001_initial"]} if database == "product" else {},
                ),
            ):
                with self.assertRaisesRegex(EnvironmentMigrationsPending, "unapplied Django migrations"):
                    PreparedEnvironment.restore(dataset, workspace)
            self.assertFalse(workspace.exists())

    @parameterized.expand(["manifest", "events"])
    def test_changed_source_refuses_restore_before_writes(self, changed: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = make_environment(root / "source")
            path = dataset.path if changed == "manifest" else dataset.path.parent / dataset.manifest.events[0].path
            with path.open("ab") as content:
                content.write(b" ")
            with override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None), self.assertRaises(ValueError):
                PreparedEnvironment.restore(dataset, root / "import")
            self.assertFalse((root / "import").exists())


@override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None)
class TestEnvironmentRestore(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            patch(
                "products.posthog_ai.eval_harness.environment.restore.collect_unapplied_product_migrations",
                return_value={},
            )
        )

    def test_restores_events_and_metrics_without_changing_operator_and_reuses_receipt(self) -> None:
        metric_id = uuid4()
        person_id = uuid4()
        target = datetime.now(UTC).replace(microsecond=345678)
        source_time = SOURCE - timedelta(minutes=2)
        event = EnvironmentEvent(
            uuid=uuid4(),
            event="delivery",
            distinct_id="00123",
            person_id=person_id,
            timestamp=source_time,
            created_at=SOURCE - timedelta(minutes=1),
            properties={"attempts": 2, "ok": False, "nested": {"value": None}, "empty": "", "mixed": [0, "0"]},
        )
        metric = EnvironmentMetric(
            id=metric_id,
            created_at=source_time,
            name="delivery_total",
            description="Count invented delivery events.",
            definition={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            referenced_table_names=["events"],
            status="approved",
            approved_at=source_time,
            owner_id=9876,
            approved_by_id=9876,
            created_by_id=9876,
        )
        original = User.objects.values(
            "email", "password", "is_staff", "current_organization_id", "current_team_id"
        ).get(id=self.user.id)
        events = [event, *(event.model_copy(update={"uuid": uuid4()}) for _ in range(5_000))]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = make_environment(root / "source", events=events, metrics=[metric], timezone="Asia/Kolkata")
            workspace = root / "import"
            with patch("posthog.models.event.util.bulk_create_events", side_effect=AssertionError("test writer used")):
                result = PreparedEnvironment.restore(dataset, workspace, target_cutoff=target, user_id=self.user.id)
                again = PreparedEnvironment.restore(dataset, workspace)
            self.assertEqual(result.event_count, len(events))
            self.assertEqual(result.metric_count, 1)
            self.assertFalse(result.reused)
            self.assertTrue(again.reused)
            self.assertEqual(again.team_id, result.team_id)
            self.assertEqual(again.target_cutoff, target)
            self.assertEqual(workspace.stat().st_mode & 0o777, 0o700)
            self.assertEqual((workspace / "receipt.json").stat().st_mode & 0o777, 0o600)
            self.assertFalse((workspace / "login-credentials.json").exists())
            receipt = PreparedEnvironment.read_receipt(workspace)
            assert receipt is not None and receipt.event_ingestion is not None
            protection = receipt.event_ingestion
            filter_bytecode = protection.filters["bytecode"]
            assert isinstance(filter_bytecode, list)
            self.assertTrue(execute_bytecode(filter_bytecode).result)
            self.assertIsNone(
                execute_bytecode(
                    protection.bytecode, globals={"event": "invented_capture", "properties": {"extra": 1}}
                ).result
            )
            self.assertEqual(
                User.objects.values("email", "password", "is_staff", "current_organization_id", "current_team_id").get(
                    id=self.user.id
                ),
                original,
            )
            team = Team.objects.get(id=result.team_id)
            self.assertEqual(team.timezone, "Asia/Kolkata")
            self.assertTrue(team.ingested_event)
            self.assertTrue(team.completed_snippet_onboarding)
            organization = Organization.objects.get(id=result.organization_id)
            self.assertFalse(organization.is_ai_data_processing_approved)
            self.assertFalse(organization.is_ai_training_opted_in)
            restored_metric = Metric.objects.for_team(team.id).get()
            self.assertEqual(restored_metric.owner_id, self.user.id)
            self.assertEqual(restored_metric.approved_by_id, self.user.id)
            self.assertEqual(restored_metric.created_by_id, self.user.id)
            self.assertNotEqual(restored_metric.id, metric_id)
            self.assertEqual(restored_metric.created_at, source_time + (target - SOURCE))
            self.assertTrue(EventDefinition.objects.filter(team_id=team.id, name="delivery").exists())
            self.assertTrue(PropertyDefinition.objects.filter(team_id=team.id, name="attempts").exists())
            rows = execute_hogql_query(
                "SELECT uuid, distinct_id, person_id, timestamp, created_at, properties.attempts, properties.ok, "
                "properties.empty, properties.mixed FROM events WHERE uuid = {event_uuid}",
                team=team,
                placeholders={"event_uuid": ast.Constant(value=str(event.uuid))},
            ).results
            self.assertEqual(len(rows or []), 1)
            assert rows is not None
            self.assertEqual(str(rows[0][0]), str(event.uuid))
            self.assertEqual(rows[0][1], "00123")
            self.assertEqual(str(rows[0][2]), str(person_id))
            self.assertEqual(rows[0][3], target - timedelta(minutes=2))
            self.assertEqual(rows[0][4], target - timedelta(minutes=1))
            self.assertEqual(rows[0][5:8], (2, False, None if use_new_events_schema(team.id) else ""))
            self.assertEqual(json.loads(rows[0][8]) if isinstance(rows[0][8], str) else rows[0][8], [0, "0"])
            stored_properties = sync_execute(
                "SELECT properties FROM events WHERE team_id = %(team_id)s AND uuid = %(uuid)s",
                {"team_id": team.id, "uuid": str(event.uuid)},
            )[0][0]
            self.assertEqual(json.loads(stored_properties), event.properties)
            for cutoff, user_id in ((target + timedelta(days=1), self.user.id), (target, self.user.id + 100000)):
                with self.assertRaisesRegex(ValueError, "different import inputs"):
                    PreparedEnvironment.restore(dataset, workspace, target_cutoff=cutoff, user_id=user_id)
            for changed in ({"enabled": False}, {"deleted": True}, {"filters": {"events": [{"id": "delivery"}]}}):
                HogFunction.objects.filter(id=protection.id, team_id=team.id).update(**changed)
                with self.assertRaisesRegex(ValueError, "event-ingestion protection is missing or changed"):
                    PreparedEnvironment.restore(dataset, workspace)
                HogFunction.objects.filter(id=protection.id, team_id=team.id).update(
                    enabled=True, deleted=False, filters=protection.filters
                )
            for field, value in (
                ("definition", {"kind": "HogQLQuery", "query": "SELECT 0"}),
                ("owner_id", None),
                ("reasoning", "changed"),
                ("last_run_at", target),
            ):
                previous = getattr(restored_metric, field)
                Metric.objects.for_team(team.id).filter(id=restored_metric.id).update(**{field: value})
                with self.assertRaisesRegex(ValueError, "restored metric changed"):
                    PreparedEnvironment.restore(dataset, workspace)
                Metric.objects.for_team(team.id).filter(id=restored_metric.id).update(**{field: previous})

    @parameterized.expand(["storage", "team_schema"])
    def test_failed_import_cannot_append_on_retry(self, failure: str) -> None:
        def fail_insert(query: str, params: dict[str, object] | None = None) -> object:
            if failure == "team_schema" and "system.functions" in query:
                return []
            if query.lstrip().startswith("INSERT"):
                raise RuntimeError("storage unavailable")
            return sync_execute(query, params)

        before = (Organization.objects.count(), Team.objects.count(), User.objects.count())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = make_environment(
                root / "source",
                events=[
                    EnvironmentEvent(
                        uuid=uuid4(),
                        event="delivery",
                        distinct_id="reader",
                        timestamp=SOURCE - timedelta(minutes=2),
                        created_at=SOURCE - timedelta(minutes=1),
                        properties={},
                    )
                ],
            )
            workspace = root / "import"
            with (
                patch("products.posthog_ai.eval_harness.environment.events.sync_execute", side_effect=fail_insert),
                patch(
                    "products.posthog_ai.eval_harness.environment.events.use_new_events_schema",
                    side_effect=(
                        (lambda team_id=None: team_id is not None)
                        if failure == "team_schema"
                        else use_new_events_schema
                    ),
                ),
            ):
                expected = (
                    "native JSON cleanup function is not ready" if failure == "team_schema" else "storage unavailable"
                )
                with self.assertRaisesRegex(RuntimeError, expected):
                    PreparedEnvironment.restore(dataset, workspace, user_id=self.user.id)
            receipt = PreparedEnvironment.read_receipt(workspace)
            assert receipt is not None
            self.assertEqual(receipt.phase, "failed")
            if failure == "team_schema":
                self.assertIsNone(receipt.team_id)
                self.assertEqual((Organization.objects.count(), Team.objects.count(), User.objects.count()), before)
            else:
                self.assertIsNotNone(receipt.team_id)
            before_retry = Team.objects.count()
            with self.assertRaisesRegex(ValueError, "incomplete"):
                PreparedEnvironment.restore(dataset, workspace, user_id=self.user.id)
            self.assertEqual(Team.objects.count(), before_retry)

    def test_empty_devbox_gets_private_login_without_resetting_existing_accounts(self) -> None:
        User.objects.filter(is_active=True).update(is_active=False)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = make_environment(root / "source")
            result = PreparedEnvironment.restore(dataset, root / "import")
            assert result.credentials_path is not None
            credentials = json.loads(result.credentials_path.read_text())
            self.assertEqual(result.credentials_path.stat().st_mode & 0o777, 0o600)
            user = User.objects.get(id=result.user_id)
            self.assertEqual(user.email, credentials["email"])
            self.assertTrue(user.check_password(credentials["password"]))
            self.assertFalse(user.is_staff)
            self.assertNotIn(credentials["password"], result.model_dump_json())
            self.assertNotIn(credentials["password"], result.receipt_path.read_text())
