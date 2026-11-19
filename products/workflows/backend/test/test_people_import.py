import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    NonAtomicBaseTest,
    _create_person,
    flush_persons_and_events,
)
from unittest.mock import MagicMock, patch

from django.db import connection, transaction
from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized
from rest_framework import status

from posthog.api.capture import CaptureInternalResult
from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
from products.cohorts.backend.models.cohort import Cohort
from products.event_definitions.backend.models import PropertyDefinition
from products.workflows.backend.facade.contracts import PeopleImportInvalid
from products.workflows.backend.models.people_import_batch import PeopleImportBatch
from products.workflows.backend.services import people_import, provider_contacts
from products.workflows.backend.services.people_import import start_people_import
from products.workflows.backend.tasks import people_import as people_import_tasks
from products.workflows.backend.tasks.people_import import (
    capture_people_import,
    fail_people_import_if_stalled,
    fill_people_import_batch,
    fill_people_import_cohort,
    finish_people_import,
)


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def write(self, key: str, content: str) -> None:
        self.objects[key] = content

    def read(self, key: str, *, missing_ok: bool = False) -> str | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class _StorageMixin:
    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        self.storage = _MemoryStorage()
        patcher = patch.object(people_import, "object_storage", self.storage)
        patcher.start()
        self.addCleanup(patcher.stop)  # type: ignore[attr-defined]
        dispatch = patch("products.workflows.backend.tasks.people_import.capture_people_import.delay")
        self.dispatch = dispatch.start()
        self.addCleanup(dispatch.stop)  # type: ignore[attr-defined]
        stall_check = patch("products.workflows.backend.tasks.people_import.fail_people_import_if_stalled.apply_async")
        self.stall_check = stall_check.start()
        self.addCleanup(stall_check.stop)  # type: ignore[attr-defined]

    def stored_people(self) -> list[dict[str, Any]]:
        [content] = (content for key, content in self.storage.objects.items() if not key.endswith(".phase.json"))
        return json.loads(content)


class TestPeopleImport(_StorageMixin, ClickhouseTestMixin, BaseTest):
    def test_each_row_writes_to_the_right_person(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"], properties={"email": "ada@example.com"})
        _create_person(team=self.team, distinct_ids=["b-newer"], properties={"email": "grace@example.com"})
        flush_persons_and_events()
        rows: list[dict[str, str]] = [
            {"Email": "ada@example.com", "Distinct ID": "user-1", "subscriptionPlan": "Pro", "company": " ", " ": ""},
            {"Email": "Grace@Example.com", "subscriptionPlan": "Free"},
            {"Email": "new@example.com", "Distinct ID": "user-9", "subscriptionPlan": "Team"},
            {"Email": "lead@example.com", "subscriptionPlan": "Trial"},
            {"Email": "not-an-email", "subscriptionPlan": "Free"},
            {"Email": "LEAD@example.com", "subscriptionPlan": "Duplicate"},
            {"Email": "big@example.com", "subscriptionPlan": "x" * 5000},
            {"Email": "other@example.com", "Distinct ID": "user-1", "subscriptionPlan": "Same person twice"},
        ]

        with self.captureOnCommitCallbacks(execute=True):
            summary = start_people_import(team=self.team, user=self.user, name="Spring sale", rows=rows)

        assert [(p["distinct_id"], p["properties"]) for p in self.stored_people()] == [
            ("user-1", {"email": "ada@example.com", "subscriptionPlan": "Pro"}),
            ("b-newer", {"email": "Grace@Example.com", "subscriptionPlan": "Free"}),
            ("user-9", {"email": "new@example.com", "subscriptionPlan": "Team"}),
            ("lead@example.com", {"email": "lead@example.com", "subscriptionPlan": "Trial"}),
        ]
        assert (summary.row_count, summary.new_people, summary.columns) == (4, 2, ["email", "subscriptionPlan"])
        assert (summary.dropped_invalid_email, summary.dropped_duplicate_email, summary.dropped_too_large) == (1, 2, 1)
        cohort = Cohort.objects.get(pk=summary.cohort_id)
        assert (cohort.team_id, cohort.name, cohort.is_static, cohort.is_calculating) == (
            self.team.id,
            "Spring sale",
            True,
            True,
        )
        self.dispatch.assert_called_once()
        assert self.stall_check.call_args.kwargs["countdown"] == 3600

    def test_an_import_into_an_existing_cohort_can_skip_new_people_and_events(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"], properties={"email": "ada@example.com"})
        flush_persons_and_events()
        cohort = Cohort.objects.create(team=self.team, name="Pro customers", is_static=True)
        rows = [{"email": "Ada@example.com", "plan": "Pro"}, {"email": "new@example.com", "plan": "Free"}]

        with (
            patch("products.workflows.backend.tasks.people_import.schedule_people_import_fill") as fill,
            self.captureOnCommitCallbacks(execute=True),
        ):
            summary = start_people_import(
                team=self.team,
                user=self.user,
                name="Ignored",
                rows=rows,
                cohort_id=cohort.id,
                create_missing=False,
                send_events=False,
            )

        assert [(p["distinct_id"], p["properties"]) for p in self.stored_people()] == [
            ("user-1", {"email": "Ada@example.com", "plan": "Pro"})
        ]
        assert (summary.cohort_id, summary.row_count, summary.new_people, summary.skipped_new_people) == (
            cohort.id,
            1,
            0,
            1,
        )
        self.dispatch.assert_not_called()
        assert fill.call_args.kwargs["cohort_id"] == cohort.id
        assert Cohort.objects.filter(team=self.team).count() == 1
        cohort.refresh_from_db()
        assert cohort.is_calculating

    def test_a_rolled_back_caller_sends_no_events_and_still_cleans_up(self) -> None:
        with self.captureOnCommitCallbacks(execute=True), self.assertRaises(RuntimeError):
            with transaction.atomic():
                start_people_import(team=self.team, user=self.user, name="List", rows=[{"email": "a@example.com"}])
                raise RuntimeError("a later list failed")

        self.dispatch.assert_not_called()
        # The stall check deletes the stored rows once the hour is up, because nothing else will.
        assert self.stall_check.call_args.kwargs["countdown"] == 3600

    @patch("products.workflows.backend.tasks.people_import.calculate_cohort_from_list.apply_async")
    @patch("products.workflows.backend.tasks.people_import.fill_people_import_batch.delay")
    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    def test_a_long_list_fills_its_cohort_once_after_every_part_whatever_the_order(
        self, _schedule: MagicMock, fill_batch: MagicMock, calculate: MagicMock
    ) -> None:
        rows = [{"email": f"person{i}@example.com"} for i in range(5)]

        with patch.object(provider_contacts, "MAX_PEOPLE_IMPORT_ROWS", 2), self.captureOnCommitCallbacks(execute=True):
            result = provider_contacts.import_provider_contacts(
                self.team.id,
                self.user.id,
                rows,
                create_people=True,
                send_events=False,
                cohort_name="VIPs",
                cohort_description="Imported from a test list.",
                source='the test list "VIPs"',
            )

        keys = sorted(
            (key for key in self.storage.objects if not key.endswith(".phase.json")),
            key=lambda key: json.loads(self.storage.objects[key])[0]["distinct_id"],
        )
        assert (result.people, len(keys)) == (5, 3)
        assert result.cohort_id is not None
        everyone = [f"person{i}@example.com" for i in range(5)]
        with patch.object(
            people_import, "get_person_uuids_and_matched_distinct_ids", side_effect=lambda _team, ids: ([], set(ids))
        ):
            for key in (keys[2], keys[0]):
                fill_people_import_cohort(team_id=self.team.id, cohort_id=result.cohort_id, storage_key=key, attempt=0)
                fill_batch.assert_not_called()
            fill_people_import_cohort(team_id=self.team.id, cohort_id=result.cohort_id, storage_key=keys[1], attempt=0)
            # A part ingestion sends twice counts once.
            fill_people_import_cohort(team_id=self.team.id, cohort_id=result.cohort_id, storage_key=keys[1], attempt=0)

        calculate.assert_not_called()
        assert Cohort.objects.get(pk=result.cohort_id).is_calculating
        fill_batch.assert_called_once()
        fill_people_import_batch(**fill_batch.call_args.kwargs)

        calculate.assert_called_once()
        assert calculate.call_args.kwargs["args"] == [result.cohort_id, everyone]
        link = calculate.call_args.kwargs["link"].kwargs
        assert link["storage_keys"] == keys
        finish_people_import(**link)
        assert self.storage.objects == {}
        assert not PeopleImportBatch.objects.for_team(self.team.id).exists()

    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    def test_a_part_with_no_valid_address_counts_as_ready_instead_of_failing_the_list(
        self, _schedule: MagicMock
    ) -> None:
        rows = [{"email": "a@example.com"}, {"email": "b@example.com"}, {"email": "not-an-email"}]

        with patch.object(provider_contacts, "MAX_PEOPLE_IMPORT_ROWS", 2), self.captureOnCommitCallbacks(execute=True):
            result = provider_contacts.import_provider_contacts(
                self.team.id,
                self.user.id,
                rows,
                create_people=True,
                send_events=False,
                cohort_name="VIPs",
                cohort_description="Imported from a test list.",
                source='the test list "VIPs"',
            )

        assert (result.status, result.people, result.dropped) == ("created", 2, 1)
        batch = PeopleImportBatch.objects.for_team(self.team.id).get()
        assert (batch.failed, batch.ready_parts) == (False, {"1": None})

    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    @patch("products.workflows.backend.tasks.people_import.capture_batch_internal")
    def test_an_import_that_only_updates_people_leaves_the_cohort_alone(
        self, capture: MagicMock, fill: MagicMock
    ) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Resend contacts", is_static=True)
        capture.return_value.succeeded.return_value = True
        capture.return_value.retried = capture.return_value.unaccounted = []

        with self.captureOnCommitCallbacks(execute=True):
            start_people_import(
                team=self.team,
                user=self.user,
                name="Ignored",
                rows=[{"email": "a@example.com", "plan": "pro"}],
                cohort_id=cohort.id,
                fill_cohort=False,
            )
        cohort.refresh_from_db()
        assert not cohort.is_calculating
        key = self.dispatch.call_args.kwargs["storage_key"]

        capture_people_import(team_id=self.team.id, cohort_id=cohort.id, storage_key=key)
        fill_people_import_cohort(**fill.call_args.kwargs["kwargs"])

        cohort.refresh_from_db()
        assert (cohort.is_calculating, cohort.errors_calculating, cohort.last_calculation) == (False, 0, None)
        assert self.storage.objects == {}
        assert not PeopleImportBatch.objects.for_team(self.team.id).exists()

    @parameterized.expand([("committed", True, True), ("rolled_back", False, False)])
    def test_stall_check_sends_a_committed_update_only_import_whatever_the_cohort_shows(
        self, _name: str, committed: bool, sent_again: bool
    ) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Resend contacts", is_static=True)
        with self.captureOnCommitCallbacks(execute=False):
            start_people_import(
                team=self.team,
                user=self.user,
                name="Ignored",
                rows=[{"email": "a@example.com", "plan": "pro"}],
                cohort_id=cohort.id,
                fill_cohort=False,
            )
        if not committed:
            PeopleImportBatch.objects.for_team(self.team.id).delete()
        stall_kwargs = self.stall_check.call_args.kwargs["kwargs"]

        fail_people_import_if_stalled(**stall_kwargs)

        assert self.dispatch.called is sent_again
        assert (stall_kwargs["storage_key"] in self.storage.objects) is sent_again
        cohort.refresh_from_db()
        assert (cohort.is_calculating, cohort.errors_calculating) == (False, 0)

    def test_a_failed_dispatch_is_kept_for_the_stall_check_and_skips_no_other_import(self) -> None:
        self.dispatch.side_effect = [ConnectionError("broker is down"), None, None]

        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            failed = start_people_import(team=self.team, user=self.user, name="A", rows=[{"email": "a@example.com"}])
            start_people_import(team=self.team, user=self.user, name="B", rows=[{"email": "b@example.com"}])

        assert self.dispatch.call_count == 2
        cohort = Cohort.objects.get(pk=failed.cohort_id)
        assert (cohort.is_calculating, cohort.errors_calculating) == (True, 0)
        [stall_kwargs] = [
            c.kwargs["kwargs"]
            for c in self.stall_check.call_args_list
            if c.kwargs["kwargs"]["cohort_id"] == failed.cohort_id
        ]

        fail_people_import_if_stalled(**stall_kwargs)

        assert self.dispatch.call_count == 3
        assert self.dispatch.call_args.kwargs["storage_key"] == stall_kwargs["storage_key"]
        assert self.stall_check.call_args.kwargs["kwargs"] == {**stall_kwargs, "check": 1}

    @parameterized.expand(
        [
            ("id_names_the_person", {"email": "a@example.com", "ID": "user-7"}, ("user-7", {"email": "a@example.com"})),
            (
                "distinct_id_column_wins",
                {"email": "a@example.com", "distinct_id": "user-7", "id": "cio-1"},
                ("user-7", {"email": "a@example.com", "id": "cio-1"}),
            ),
        ]
    )
    def test_id_column_names_the_person_without_a_distinct_id_column(
        self, _name: str, row: dict[str, str], expected: tuple[str, dict[str, str]]
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            start_people_import(team=self.team, user=self.user, name="List", rows=[row])

        assert [(p["distinct_id"], p["properties"]) for p in self.stored_people()] == [expected]

    @parameterized.expand(
        [
            ("no_email_column", [{"name": "Ada"}], 'column named "email"', None),
            ("no_valid_email", [{"email": "nope"}], "No row has a valid email", None),
            (
                "illegal_distinct_id",
                [{"email": "a@example.com", "distinct_id": "Anonymous"}],
                'Row 2 has the distinct_id "Anonymous"',
                None,
            ),
            ("long_distinct_id", [{"email": "a@example.com", "distinct_id": "x" * 201}], "longer than 200 bytes", None),
            ("blank_header_with_data", [{"email": "a@example.com", "   ": "Hedgebox"}], "has no name", None),
            (
                "two_columns_with_one_name",
                [{"email": "a@example.com", "Email ": "b@example.com"}],
                'both named "email"',
                None,
            ),
            ("read_only_property", [{"email": "a@example.com", "plan": "Pro"}], "can't change these", "plan"),
        ]
    )
    def test_rejects_unusable_files(
        self, _name: str, rows: list[dict[str, str]], message: str, read_only_property: str | None
    ) -> None:
        if read_only_property:
            self.organization.available_product_features = [
                {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
            ]
            self.organization.save(update_fields=["available_product_features"])
            PropertyAccessControl.objects.create(
                team=self.team,
                property_definition=PropertyDefinition.objects.create(
                    team=self.team, name=read_only_property, property_type="String", type=PropertyDefinition.Type.PERSON
                ),
                access_level=PropertyAccessLevel.READ.value,
            )
        with self.assertRaises(PeopleImportInvalid) as error:
            start_people_import(team=self.team, user=self.user, name="List", rows=rows)
        assert message in str(error.exception)
        assert not Cohort.objects.filter(team_id=self.team.id).exists()

    def test_matches_by_email_with_the_importing_users_property_access(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"], properties={"email": "ada@example.com"})
        flush_persons_and_events()
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        email = PropertyDefinition.objects.create(
            team=self.team, name="email", property_type="String", type=PropertyDefinition.Type.PERSON
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=email, access_level=PropertyAccessLevel.NONE.value
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=email,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.READ_WRITE.value,
        )

        with self.captureOnCommitCallbacks(execute=True):
            start_people_import(team=self.team, user=self.user, name="List", rows=[{"email": "ada@example.com"}])

        assert [person["distinct_id"] for person in self.stored_people()] == ["user-1"]

    def test_a_list_that_fails_partway_keeps_the_spellings_of_the_parts_already_sent(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-left"], properties={"email": "Left@Example.com"})
        flush_persons_and_events()
        start = provider_contacts.start_people_import
        calls = 0

        def second_part_invalid(**kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PeopleImportInvalid("You can't change these person properties: first_name.")
            return start(**kwargs)

        with (
            patch.object(provider_contacts, "MAX_PEOPLE_IMPORT_ROWS", 1),
            patch.object(provider_contacts, "start_people_import", side_effect=second_part_invalid),
        ):
            result = provider_contacts.import_provider_contacts(
                self.team.id,
                self.user.id,
                [{"email": "left@example.com"}, {"email": "other@example.com"}],
                create_people=False,
                send_events=True,
                cohort_name="VIPs",
                cohort_description="Imported from a test list.",
                source='the test list "VIPs"',
            )

        assert (result.status, result.person_emails) == ("failed", ("Left@Example.com",))

    def test_ends_the_import_when_staging_fails(self) -> None:
        with patch.object(self.storage, "write", side_effect=ConnectionError("storage is down")):
            with self.assertRaises(ConnectionError):
                start_people_import(team=self.team, user=self.user, name="List", rows=[{"email": "a@example.com"}])

        cohort = Cohort.objects.get(team_id=self.team.id)
        assert (cohort.is_calculating, cohort.errors_calculating) == (False, 1)
        self.dispatch.assert_not_called()


class TestPeopleImportTasks(_StorageMixin, BaseTest):
    def _stage(
        self,
        distinct_ids: tuple[str, ...] = ("user-1",),
        *,
        fill_only: bool = False,
        phase: dict[str, Any] | None = None,
        calculating: bool = True,
    ) -> tuple[int, str]:
        cohort = Cohort.objects.create(team=self.team, name="List", is_static=True, is_calculating=calculating)
        key = f"workflows_people_imports/team-{self.team.id}/{cohort.pk}.json"
        if phase is not None:
            self.storage.write(
                f"workflows_people_imports/team-{self.team.id}/{cohort.pk}.phase.json", json.dumps(phase)
            )
        people = [
            {
                "distinct_id": d,
                "properties": {"email": f"{d}@example.com"},
                **({"fill_only": True} if fill_only else {}),
            }
            for d in distinct_ids
        ]
        self.storage.write(key, json.dumps(people))
        return cohort.pk, key

    @parameterized.expand([("overwrites", False, "$set"), ("fills_only_what_is_missing", True, "$set_once")])
    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    @patch("products.workflows.backend.tasks.people_import.capture_batch_internal")
    def test_capture_sets_each_row_on_its_person(
        self, _name: str, fill_only: bool, operation: str, capture: MagicMock, fill: MagicMock
    ) -> None:
        cohort_id, key = self._stage(fill_only=fill_only)
        capture.return_value.succeeded.return_value = True

        capture_people_import(team_id=self.team.id, cohort_id=cohort_id, storage_key=key)

        [event] = capture.call_args.kwargs["events"]
        assert (event["event"], event["distinct_id"], event["properties"]) == (
            "$set",
            "user-1",
            {operation: {"email": "user-1@example.com"}, "$geoip_disable": True},
        )
        assert capture.call_args.kwargs["process_person_profile"] is True
        fill.assert_called_once()

    @parameterized.expand([("capture_raises", ConnectionError("capture is down")), ("capture_acks_nothing", None)])
    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    @patch("products.workflows.backend.tasks.people_import.capture_batch_internal")
    def test_capture_closes_the_import_after_the_last_retry(
        self, _name: str, error: Exception | None, capture: MagicMock, fill: MagicMock
    ) -> None:
        cohort_id, key = self._stage()
        capture.side_effect = error or (
            lambda events, **_: CaptureInternalResult(status_code=503, unaccounted=[e["event_uuid"] for e in events])
        )

        capture_people_import.apply(
            kwargs={"team_id": self.team.id, "cohort_id": cohort_id, "storage_key": key},
            retries=people_import_tasks.CAPTURE_MAX_RETRIES,
        )

        cohort = Cohort.objects.get(pk=cohort_id)
        assert (cohort.is_calculating, cohort.errors_calculating) == (False, 1)
        assert key not in self.storage.objects
        fill.assert_not_called()

    @parameterized.expand(
        [
            ("partial_ack", None, {"ok": ["user-1"], "retried": ["user-2"]}, ["user-1", "user-2"], ["user-2"]),
            ("dropped_only", None, {"ok": ["user-1"], "dropped": ["user-2"]}, ["user-1", "user-2"], None),
            ("retry_of_a_subset", ["user-2"], {"ok": ["user-2"]}, ["user-2"], None),
        ]
    )
    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    @patch("products.workflows.backend.tasks.people_import.capture_batch_internal")
    def test_capture_resends_only_unacknowledged_events(
        self,
        _name: str,
        pending: list[str] | None,
        buckets: dict[str, list[str]],
        sent: list[str],
        retried: list[str] | None,
        capture: MagicMock,
        fill: MagicMock,
    ) -> None:
        cohort_id, key = self._stage(("user-1", "user-2"))

        def submit(events: list[dict], **_: object) -> CaptureInternalResult:
            uuid_of = {event["distinct_id"]: event["event_uuid"] for event in events}

            def uuids(bucket: str) -> list[str]:
                return [uuid_of[distinct_id] for distinct_id in buckets.get(bucket, [])]

            return CaptureInternalResult(
                status_code=200, ok=uuids("ok"), dropped=uuids("dropped"), retried=uuids("retried")
            )

        capture.side_effect = submit
        with patch.object(capture_people_import, "retry", return_value=Retry()) as retry:
            try:
                capture_people_import(
                    team_id=self.team.id, cohort_id=cohort_id, storage_key=key, pending_distinct_ids=pending
                )
            except Retry:
                pass

        assert [event["distinct_id"] for event in capture.call_args.kwargs["events"]] == sent
        retried_ids = retry.call_args.kwargs["kwargs"]["pending_distinct_ids"] if retry.called else None
        assert (retried_ids, fill.called) == (retried, retried is None)

    @parameterized.expand(
        [
            ("still_missing", ([], set()), 0, "waits"),
            ("all_found", ([], {"user-1"}), 0, "fills"),
            ("lookup_fails", ConnectionError("personhog is down"), 0, "waits"),
            ("lookup_fails_on_the_last_attempt", ConnectionError("personhog is down"), 7, "fails"),
        ]
    )
    @patch("products.workflows.backend.tasks.people_import.calculate_cohort_from_list.apply_async")
    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    def test_fill_waits_for_ingestion(
        self,
        _name: str,
        lookup: tuple[list[str], set[str]] | Exception,
        attempt: int,
        outcome: str,
        reschedule: MagicMock,
        calculate: MagicMock,
    ) -> None:
        cohort_id, key = self._stage()

        with patch.object(people_import, "get_person_uuids_and_matched_distinct_ids", side_effect=[lookup]):
            fill_people_import_cohort(team_id=self.team.id, cohort_id=cohort_id, storage_key=key, attempt=attempt)

        cohort = Cohort.objects.get(pk=cohort_id)
        assert reschedule.called is (outcome == "waits")
        assert calculate.called is (outcome == "fills")
        # The rows stay until the population succeeds, so the stall check still follows the import.
        assert (key in self.storage.objects) is (outcome != "fails")
        assert cohort.is_calculating is (outcome != "fails")
        if outcome == "fills":
            assert calculate.call_args.kwargs["link"].kwargs == {
                "team_id": self.team.id,
                "storage_keys": [key],
                "batch_id": None,
            }
            finish_people_import(**calculate.call_args.kwargs["link"].kwargs)
            assert key not in self.storage.objects

    @patch("products.workflows.backend.tasks.people_import.fill_people_import_batch.delay")
    def test_stall_check_fills_a_complete_batch_whose_fill_was_lost(self, fill_batch: MagicMock) -> None:
        batch = PeopleImportBatch.objects.for_team(self.team.id).create(
            team=self.team, cohort_id=0, parts=2, ready_parts={"0": "a", "1": "b"}
        )
        cohort_id, key = self._stage(phase={"phase": "waiting_for_parts", "batch": [str(batch.id), 1]})

        other_id, other_key = self._stage(phase={"phase": "waiting_for_parts", "batch": [str(batch.id), 0]})

        fail_people_import_if_stalled(team_id=self.team.id, cohort_id=cohort_id, storage_key=key)
        # The other part's check runs before the fill starts, and leaves the fill to the first.
        fail_people_import_if_stalled(team_id=self.team.id, cohort_id=other_id, storage_key=other_key)

        fill_batch.assert_called_once_with(team_id=self.team.id, batch_id=str(batch.id))
        assert self.stall_check.call_args.kwargs["kwargs"]["check"] == 1

    @patch("products.workflows.backend.tasks.people_import.calculate_cohort_from_list.apply_async")
    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    def test_fill_retries_a_storage_error_after_capture_without_sending_again(
        self, reschedule: MagicMock, calculate: MagicMock
    ) -> None:
        cohort_id, key = self._stage(phase={"phase": "dispatched"})
        read = self.storage.read

        def phase_unreadable(storage_key: str, *, missing_ok: bool = False) -> str | None:
            if storage_key.endswith(".phase.json"):
                raise ConnectionError("storage is down")
            return read(storage_key, missing_ok=missing_ok)

        with patch.object(self.storage, "read", side_effect=phase_unreadable):
            fill_people_import_cohort(team_id=self.team.id, cohort_id=cohort_id, storage_key=key, attempt=0)

        assert reschedule.call_args.kwargs["kwargs"]["attempt"] == 1
        calculate.assert_not_called()
        self.dispatch.assert_not_called()
        assert key in self.storage.objects

    def test_stall_check_retries_a_storage_error_with_the_same_check(self) -> None:
        cohort_id, key = self._stage()

        with (
            patch.object(self.storage, "read", side_effect=ConnectionError("storage is down")),
            patch.object(fail_people_import_if_stalled, "retry", return_value=Retry()) as retry,
            self.assertRaises(Retry),
        ):
            fail_people_import_if_stalled(team_id=self.team.id, cohort_id=cohort_id, storage_key=key, check=2)

        retry.assert_called_once()
        assert key in self.storage.objects

    @parameterized.expand(
        [
            # (name, phase, cohort calculating, earlier attempt, attempt since, check, rows kept, errors, checks again)
            ("finished", None, True, False, False, 0, False, 0, False),
            ("rolled_back", "staged", False, False, False, 0, False, 0, False),
            ("dispatch_never_ran", "staged", True, False, False, 0, True, 0, True),
            ("dispatch_failed", "dispatch_failed", True, False, False, 0, True, 0, True),
            ("dispatch_failed_on_the_last_check", "dispatch_failed", True, False, False, 5, False, 1, False),
            ("capture_stalled", "dispatched", True, False, False, 0, False, 1, False),
            ("population_running", "populating", True, True, True, 0, True, 0, True),
            ("population_running_too_long", "populating", True, True, True, 5, False, 1, False),
            ("population_lost_on_a_reused_cohort", "populating", True, True, False, 0, False, 1, False),
            ("population_ended_without_cleanup", "populating", False, True, True, 0, False, 0, False),
            ("other_parts_still_coming", "waiting_for_parts", True, False, False, 0, True, 0, True),
            ("other_parts_never_came", "waiting_for_parts", True, False, False, 5, False, 1, False),
        ]
    )
    def test_stall_check_follows_the_import_until_it_ends(
        self,
        _name: str,
        phase: str | None,
        calculating: bool,
        earlier_attempt: bool,
        attempt_since: bool,
        check: int,
        rows_kept: bool,
        errors: int,
        checks_again: bool,
    ) -> None:
        started = timezone.now() - timedelta(hours=2)
        batch = PeopleImportBatch.objects.for_team(self.team.id).create(team=self.team, cohort_id=0, parts=2)
        cohort_id, key = self._stage(
            phase={
                "phase": phase,
                "at": started.isoformat(),
                "send_events": True,
                **({"batch": [str(batch.id), 0]} if phase == "waiting_for_parts" else {}),
            }
            if phase
            else None,
            calculating=calculating,
        )
        if phase is None:
            self.storage.delete(key)
        if earlier_attempt:
            CohortCalculationHistory.objects.create(
                team=self.team,
                cohort_id=cohort_id,
                filters={},
                started_at=started - timedelta(days=1),
                finished_at=started,
            )
        if attempt_since:
            CohortCalculationHistory.objects.create(team=self.team, cohort_id=cohort_id, filters={}, started_at=started)

        fail_people_import_if_stalled(team_id=self.team.id, cohort_id=cohort_id, storage_key=key, check=check)

        cohort = Cohort.objects.get(pk=cohort_id)
        assert (key in self.storage.objects, cohort.errors_calculating) == (rows_kept, errors)
        assert self.stall_check.called is checks_again
        assert self.dispatch.called is (phase in ("staged", "dispatch_failed") and checks_again)


class TestPeopleImportBatchConcurrency(NonAtomicBaseTest):
    def test_two_parts_finishing_together_complete_the_batch_exactly_once(self) -> None:
        batch = PeopleImportBatch.objects.for_team(self.team.id).create(
            team=self.team, cohort_id=1, parts=3, ready_parts={"0": "part-0"}
        )
        # Both parts reach the write together unless the lock holds one back until the other commits.
        together = threading.Barrier(2, timeout=2)
        save = PeopleImportBatch.save

        def save_together(instance: PeopleImportBatch, *args: Any, **kwargs: Any) -> None:
            try:
                together.wait()
            except threading.BrokenBarrierError:
                pass
            save(instance, *args, **kwargs)

        def finish(part: int) -> bool:
            try:
                return people_import.mark_people_import_part_ready(self.team.id, batch.id, part, f"part-{part}")
            finally:
                connection.close()

        with patch.object(PeopleImportBatch, "save", save_together), ThreadPoolExecutor(max_workers=2) as pool:
            completed = list(pool.map(finish, (1, 2)))

        assert sorted(completed) == [False, True]
        batch = PeopleImportBatch.objects.for_team(self.team.id).get(id=batch.id)
        assert batch.ready_parts == {"0": "part-0", "1": "part-1", "2": "part-2"}


class TestPeopleImportAPI(_StorageMixin, ClickhouseTestMixin, APIBaseTest):
    def test_import_returns_its_cohort_and_rejects_an_unusable_file(self) -> None:
        url = f"/api/projects/{self.team.id}/workflow_people_imports/"

        created = self.client.post(
            url, {"name": "List", "rows": [{"email": "a@example.com", "org": "Acme"}]}, format="json"
        )
        rejected = self.client.post(url, {"name": "List", "rows": [{"name": "Ada"}]}, format="json")

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        assert created.json()["columns"] == ["email", "org"]
        assert Cohort.objects.filter(pk=created.json()["cohort_id"], team_id=self.team.id).exists()
        assert rejected.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([("person_viewer", "viewer", 403), ("person_editor", "editor", 201)])
    def test_import_needs_person_edit_access(self, _name: str, person_access: str, expected_status: int) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(team=self.team, resource="person", resource_id=None, access_level=person_access)

        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_people_imports/",
            {"name": "List", "rows": [{"email": "a@example.com"}]},
            format="json",
        )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [("cohort_only", ["cohort:write"], 403), ("cohort_and_person", ["cohort:write", "person:write"], 201)]
    )
    def test_import_needs_person_write_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="t", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_people_imports/",
            {"name": "List", "rows": [{"email": "a@example.com"}]},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == expected_status, response.json()
