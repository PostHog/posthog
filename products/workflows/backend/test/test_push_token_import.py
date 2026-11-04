from datetime import timedelta
from typing import Any
from uuid import UUID

import time_machine
from posthog.test.base import APIBaseTest, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.api.capture import CaptureInternalResult
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.workflows.backend.facade.contracts import PushTokenImportInvalid, PushTokenImportRecord
from products.workflows.backend.facade.enums import PushTokenImportRowFailureReason, PushTokenImportStatus
from products.workflows.backend.models.push_token_import import PushTokenImport
from products.workflows.backend.services import push_token_import
from products.workflows.backend.services.push_token_import import (
    cancel_push_token_import,
    check_stalled_push_token_import,
    get_push_token_import,
    import_unknown_persons,
    parse_push_token_csv,
    run_push_token_import_batches,
    start_push_token_import,
)

APNS_TOKEN = "a1" * 32


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def write(self, key: str, content: bytes) -> None:
        self.objects[key] = content

    def read_bytes(self, key: str, *, missing_ok: bool = False) -> bytes | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class TestParsePushTokenCsv(SimpleTestCase):
    @parameterized.expand(
        [
            ("not_utf8", "distinct_id,device_token\nuser-é,abc\n".encode("latin-1"), "isn't saved as UTF-8"),
            ("missing_column", b"distinct_id,token\nuser-1,abc\n", "needs a distinct_id column"),
            ("only_header", b"distinct_id,device_token\n\n , \n", "only the column names"),
            ("empty", b"", "The file is empty"),
            ("broken_quotes", b'distinct_id,device_token\n"user-1,abc\n', "can't be read"),
            ("too_many_lines", b"distinct_id,device_token\nuser-1,abc" + b"\n" * 400_001, "more than 400,000 lines"),
        ]
    )
    def test_rejects_a_file_it_cannot_use(self, _name: str, content: bytes, message: str) -> None:
        with self.assertRaisesMessage(PushTokenImportInvalid, message):
            parse_push_token_csv(content)

    def test_reads_devices_with_the_line_each_came_from(self) -> None:
        content = (
            "﻿Name,Distinct_ID , DEVICE_TOKEN\n"
            '"Ada\nLovelace",user-1,tok-1\n'
            "\n"
            "Bob,user-2,tok-2\n"
            "Bob again,user-2,tok-2\n"
            "No id,,tok-3\n"
            f"Long,user-4,{'x' * 4097}\n"
            "Ünï 🎉,user-🎉,tok-5\n"
            "Nul,,tok\x00\n"
            f"Emoji,{'🎉' * 51},tok-6\n"
        ).encode()

        parsed = parse_push_token_csv(content)

        assert parsed.devices == [
            {"line": 2, "distinct_id": "user-1", "device_token": "tok-1"},
            {"line": 5, "distinct_id": "user-2", "device_token": "tok-2"},
            {"line": 9, "distinct_id": "user-🎉", "device_token": "tok-5"},
        ]
        assert [(failure.line, failure.detail) for failure in parsed.rejected] == [
            (7, "No distinct ID"),
            (8, "Device token is longer than 4096 characters"),
            (10, "The line has a NUL character in it"),
            (11, "Distinct ID is longer than 200 bytes"),
        ]
        assert parsed.duplicate_lines == 1


class _PushTokenImportTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.apns = Integration.objects.create(
            team=self.team,
            kind="apns",
            integration_id="TEAM.com.example.app",
            config={"bundle_id": "com.example.app", "team_id": "TEAM", "key_id": "KEY"},
        )
        self.storage = _MemoryStorage()
        patchers: list[Any] = [
            patch.object(push_token_import, "object_storage", self.storage),
            patch.object(push_token_import, "BATCH_SIZE", 2),
            patch.object(push_token_import, "BATCHES_PER_TASK", 1),
            patch("products.workflows.backend.tasks.push_token_import.run_push_token_import.delay"),
            patch("products.workflows.backend.tasks.push_token_import.check_push_token_import_stalled.apply_async"),
            patch.object(push_token_import, "ph_scoped_capture"),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        expire = patch(
            "products.workflows.backend.tasks.push_token_import.expire_push_token_import_devices.apply_async"
        )
        self.schedule_expiry = expire.start()
        self.addCleanup(expire.stop)
        self.captured: list[list[dict[str, Any]]] = []
        self.drop_once: set[str] = set()
        capture = patch("posthog.api.integration_push_tokens.capture_batch_internal", side_effect=self._capture)
        capture.start()
        self.addCleanup(capture.stop)

    def _capture(self, *, events: list[dict[str, Any]], **kwargs: Any) -> CaptureInternalResult:
        self.captured.append(events)
        result = CaptureInternalResult(status_code=200)
        for event in events:
            dropped = event["distinct_id"] in self.drop_once
            self.drop_once.discard(event["distinct_id"])
            (result.dropped if dropped else result.ok).append(event["event_uuid"])
        return result

    def _upload(self, lines: list[str], *, create_missing_persons: bool = False) -> PushTokenImportRecord:
        return start_push_token_import(
            team=self.team,
            user=self.user,
            integration_id=self.apns.id,
            content="\n".join(["distinct_id,device_token", *lines]).encode(),
            create_missing_persons=create_missing_persons,
        )

    def _run_to_end(self, import_id: UUID) -> PushTokenImportRecord:
        while run_push_token_import_batches(self.team.id, import_id):
            pass
        return get_push_token_import(self.team.id, import_id)


class TestPushTokenImportJob(_PushTokenImportTestCase):
    def test_imports_the_file_in_batches_and_reports_each_failed_line(self) -> None:
        for distinct_id in ["user-1", "user-2", "user-3"]:
            _create_person(team=self.team, distinct_ids=[distinct_id])
        flush_persons_and_events()

        started = self._upload(
            [
                f"user-1,{APNS_TOKEN}",
                f"user-2,{APNS_TOKEN}",
                ",missing-id",
                "user-3,ExponentPushToken[abc]",
                f"nobody,{APNS_TOKEN}",
                f"user-3,{'b2' * 32}",
            ]
        )
        assert started.status == PushTokenImportStatus.RUNNING
        kept_for = push_token_import.UNKNOWN_PERSON_DEVICES_KEPT_FOR + push_token_import.EXPIRY_MARGIN
        assert self.schedule_expiry.call_args.kwargs["countdown"] == int(kept_for.total_seconds())

        result = self._run_to_end(started.id)

        assert result.status == PushTokenImportStatus.COMPLETED
        assert [len(batch) for batch in self.captured] == [2, 1]
        assert (result.total_devices, result.imported_devices, result.failed_devices) == (5, 3, 3)
        assert sorted((failure.line, failure.reason) for failure in result.failures) == [
            (4, PushTokenImportRowFailureReason.INVALID_ROW),
            (5, PushTokenImportRowFailureReason.TOKEN_MISMATCH),
            (6, PushTokenImportRowFailureReason.UNKNOWN_PERSON),
        ]
        assert result.unknown_person_devices == 1
        assert result.can_import_unknown_persons is True

    def test_imports_the_devices_of_unknown_people_once_with_new_persons(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"])
        flush_persons_and_events()
        first = self._run_to_end(self._upload([f"user-1,{APNS_TOKEN}", f"new-1,{APNS_TOKEN}", f"new-2,{'c3' * 32}"]).id)
        self.captured.clear()

        retry = import_unknown_persons(team=self.team, user=self.user, import_id=first.id)
        with self.assertRaises(PushTokenImportInvalid):
            import_unknown_persons(team=self.team, user=self.user, import_id=first.id)

        result = self._run_to_end(retry.id)
        assert result.create_missing_persons is True
        assert (result.total_devices, result.imported_devices) == (2, 2)
        assert sorted(event["distinct_id"] for batch in self.captured for event in batch) == ["new-1", "new-2"]
        assert get_push_token_import(self.team.id, first.id).can_import_unknown_persons is False
        assert self.storage.objects == {}

    def test_a_channel_runs_one_import_at_a_time_and_a_cancelled_import_stops_sending(self) -> None:
        first = self._upload([f"user-1,{APNS_TOKEN}"])
        with self.assertRaisesRegex(PushTokenImportInvalid, "already running"):
            self._upload([f"user-2,{APNS_TOKEN}"])

        cancelled = cancel_push_token_import(self.team.id, first.id)
        result = self._run_to_end(first.id)

        assert (cancelled.status, cancelled.finished_at) == (PushTokenImportStatus.CANCELLED, None)
        assert result.status == PushTokenImportStatus.CANCELLED
        assert result.finished_at is not None
        assert self.captured == []
        assert self.storage.objects == {}
        assert self._upload([f"user-2,{APNS_TOKEN}"]).status == PushTokenImportStatus.RUNNING

    def test_a_stop_that_lands_during_a_batch_still_counts_that_batch(self) -> None:
        import_id = self._upload(
            [f"a,{APNS_TOKEN}", f"b,{APNS_TOKEN}", f"c,{APNS_TOKEN}"], create_missing_persons=True
        ).id

        def stop_while_sending(**kwargs: Any) -> CaptureInternalResult:
            cancel_push_token_import(self.team.id, import_id)
            return self._capture(**kwargs)

        with patch("posthog.api.integration_push_tokens.capture_batch_internal", side_effect=stop_while_sending):
            result = self._run_to_end(import_id)

        assert (result.status, result.processed_devices, result.imported_devices) == (
            PushTokenImportStatus.CANCELLED,
            2,
            2,
        )
        assert result.finished_at is not None
        assert self.storage.objects == {}

    @patch.object(push_token_import.time, "sleep")
    def test_a_device_ingestion_did_not_store_is_sent_again_with_its_event_id(self, _sleep: Any) -> None:
        self.drop_once = {"b"}
        import_id = self._upload([f"a,{APNS_TOKEN}", f"b,{APNS_TOKEN}"], create_missing_persons=True).id

        result = self._run_to_end(import_id)

        assert (result.imported_devices, result.failed_devices) == (2, 0)
        assert [event["distinct_id"] for event in self.captured[1]] == ["b"]
        assert self.captured[1][0]["event_uuid"] == self.captured[0][1]["event_uuid"]

    def test_a_failed_delete_keeps_the_devices_known_so_cleanup_runs_again(self) -> None:
        import_id = self._upload([f"a,{APNS_TOKEN}"], create_missing_persons=True).id
        with (
            patch.object(self.storage, "delete", side_effect=RuntimeError("storage down")),
            patch(
                "products.workflows.backend.tasks.push_token_import.expire_push_token_import_devices.apply_async"
            ) as retry_cleanup,
        ):
            self._run_to_end(import_id)

        assert PushTokenImport.objects.for_team(self.team.id).get(id=import_id).storage_key != ""
        retry_cleanup.assert_called_once()
        assert retry_cleanup.call_args.kwargs["countdown"] == int(push_token_import.DELETE_RETRY_AFTER.total_seconds())

    def test_a_batch_sent_again_after_a_crash_reuses_its_event_ids(self) -> None:
        lines = [f"a,{APNS_TOKEN}", f"b,{APNS_TOKEN}", f"c,{APNS_TOKEN}"]
        import_id = self._upload(lines, create_missing_persons=True).id
        assert run_push_token_import_batches(self.team.id, import_id) is True
        first_events = [(event["event_uuid"], event["timestamp"]) for event in self.captured[0]]
        PushTokenImport.objects.for_team(self.team.id).filter(id=import_id).update(processed_devices=0)
        self.captured.clear()

        run_push_token_import_batches(self.team.id, import_id)

        assert [(event["event_uuid"], event["timestamp"]) for event in self.captured[0]] == first_events

    def test_an_import_whose_stored_devices_are_gone_fails_instead_of_completing(self) -> None:
        import_id = self._upload([f"a,{APNS_TOKEN}"], create_missing_persons=True).id
        self.storage.objects.clear()

        result = self._run_to_end(import_id)

        assert result.status == PushTokenImportStatus.FAILED
        assert "couldn't read the stored devices" in result.error
        assert self.captured == []

    def test_a_failed_delete_does_not_let_unknown_people_be_imported_twice(self) -> None:
        first = self._run_to_end(self._upload([f"new-1,{APNS_TOKEN}"]).id)
        with patch.object(self.storage, "delete", side_effect=RuntimeError("storage down")):
            retry = import_unknown_persons(team=self.team, user=self.user, import_id=first.id)
        self._run_to_end(retry.id)

        with self.assertRaises(PushTokenImportInvalid):
            import_unknown_persons(team=self.team, user=self.user, import_id=first.id)

    def test_a_failed_row_write_deletes_the_stored_devices(self) -> None:
        with patch.object(PushTokenImport.objects, "for_team", side_effect=OperationalError("database down")):
            with self.assertRaises(OperationalError):
                self._upload([f"a,{APNS_TOKEN}"])

        assert self.storage.objects == {}

    def test_progress_during_the_last_stall_check_keeps_the_import_running(self) -> None:
        import_id = self._upload([f"user-1,{APNS_TOKEN}"]).id
        PushTokenImport.objects.for_team(self.team.id).filter(id=import_id).update(resumed_times=3)
        stale = timezone.now() - timedelta(hours=1)
        PushTokenImport.objects.for_team(self.team.id).filter(id=import_id).update(updated_at=stale)

        assert (
            push_token_import.fail_push_token_import(
                self.team.id, import_id, "stopped", unless_updated_since=stale - timedelta(seconds=1)
            )
            is False
        )

        job = PushTokenImport.objects.for_team(self.team.id).get(id=import_id)
        assert job.status == PushTokenImportStatus.RUNNING

    def test_an_import_that_stops_making_progress_is_resumed_then_failed(self) -> None:
        import_id = self._upload([f"user-1,{APNS_TOKEN}"]).id
        assert check_stalled_push_token_import(self.team.id, import_id) is True

        with patch("products.workflows.backend.tasks.push_token_import.run_push_token_import.delay") as resume:
            for minutes in [6, 12, 18]:
                with time_machine.travel(timezone.now() + timedelta(minutes=minutes), tick=False):
                    assert check_stalled_push_token_import(self.team.id, import_id) is True
            assert resume.call_count == 3
            with time_machine.travel(timezone.now() + timedelta(minutes=24), tick=False):
                assert check_stalled_push_token_import(self.team.id, import_id) is False

        job = PushTokenImport.objects.for_team(self.team.id).get(id=import_id)
        assert job.status == PushTokenImportStatus.FAILED
        assert "stopped after 0 of 1 devices" in job.error
        assert self.storage.objects == {}
