from collections.abc import Callable
from dataclasses import field
from datetime import datetime, timedelta
from functools import partial
from itertools import count
from typing import Any, Literal

import time_machine
from posthog.test.base import APIBaseTest, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connections, router
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.capture import CaptureInternalResult
from posthog.dataclasses import frozen
from posthog.models import PersonalAPIKey
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.workflows.backend.facade.contracts import PushTokenImportInvalid, PushTokenImportRecord
from products.workflows.backend.facade.enums import PushTokenImportRowFailureReason, PushTokenImportStatus
from products.workflows.backend.models.push_token_import import PushTokenImport
from products.workflows.backend.services import push_token_import
from products.workflows.backend.services.push_token_import import (
    cancel_push_token_import,
    get_push_token_import,
    import_unknown_persons,
    parse_push_token_csv,
    start_push_token_import,
)
from products.workflows.backend.tasks import push_token_import as tasks

APNS_TOKEN = "a1" * 32
THREE_DEVICES = [f"a,{APNS_TOKEN}", f"b,{APNS_TOKEN}", f"c,{APNS_TOKEN}"]


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.down = False

    def write(self, key: str, content: bytes) -> None:
        self.objects[key] = content

    def read_bytes(self, key: str, *, missing_ok: bool = False) -> bytes | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        if self.down:
            raise RuntimeError("storage down")
        self.objects.pop(key, None)


class _Ingestion:
    def __init__(self) -> None:
        self.stored_once_per_event_id_and_timestamp: dict[tuple[str, str], dict[str, Any]] = {}
        self.fails_once: dict[str, Literal["dropped", "unaccounted"]] = {}

    def capture(self, *, events: list[dict[str, Any]], **kwargs: Any) -> CaptureInternalResult:
        result = CaptureInternalResult(status_code=200)
        for event in events:
            failure = self.fails_once.pop(event["distinct_id"], None)
            if failure != "dropped":
                timestamp = str(event.get("timestamp") or timezone.now())
                self.stored_once_per_event_id_and_timestamp.setdefault((event["event_uuid"], timestamp), event)
            getattr(result, failure or "ok").append(event["event_uuid"])
        return result

    def devices(self) -> list[str]:
        return sorted(event["distinct_id"] for event in self.stored_once_per_event_id_and_timestamp.values())


@frozen(order=True)
class _Scheduled:
    due: datetime
    order: int
    task: Any = field(compare=False)
    kwargs: dict[str, Any] = field(compare=False)


class _Queue:
    def __init__(self, start: datetime) -> None:
        self.traveller = time_machine.travel(start, tick=False)
        self.clock = self.traveller.start()
        self.scheduled: list[_Scheduled] = []
        self.loses_imports = False
        self.order = count()

    def apply_async(self, task: Any, args: Any = None, kwargs: Any = None, countdown: Any = 0, **options: Any) -> None:
        if task is tasks.run_push_token_import and self.loses_imports:
            return
        due = timezone.now() + timedelta(seconds=countdown or 0)
        self.scheduled.append(_Scheduled(due=due, order=next(self.order), task=task, kwargs=kwargs))

    def sleep(self, seconds: float) -> None:
        self.clock.shift(seconds)

    def advance(self, by: timedelta = timedelta()) -> None:
        until = timezone.now() + by
        while due := sorted(entry for entry in self.scheduled if entry.due <= until):
            self.scheduled.remove(due[0])
            self.clock.move_to(max(due[0].due, timezone.now()))
            self.run(due[0].task, due[0].kwargs)
        self.clock.move_to(until)

    def run(self, task: Any, kwargs: dict[str, Any]) -> None:
        try:
            task.run(**kwargs)
        except SystemExit:
            pass


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
        self.ingestion = _Ingestion()
        self.queue = _Queue(timezone.now())
        self.addCleanup(self.queue.traveller.stop)
        patchers: list[Any] = [
            patch.object(push_token_import, "object_storage", self.storage),
            patch.object(push_token_import, "BATCH_SIZE", 2),
            patch.object(push_token_import, "BATCHES_PER_TASK", 1),
            patch.object(push_token_import.time, "sleep", side_effect=self.queue.sleep),
            patch.object(push_token_import, "ph_scoped_capture"),
            patch("posthog.api.integration_push_tokens.capture_batch_internal", side_effect=self.ingestion.capture),
        ]
        for task in (
            tasks.run_push_token_import,
            tasks.check_push_token_import_stalled,
            tasks.expire_push_token_import_devices,
        ):
            patchers.append(patch.object(task, "apply_async", side_effect=partial(self.queue.apply_async, task)))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _upload(self, lines: list[str], *, create_missing_persons: bool = False) -> PushTokenImportRecord:
        return start_push_token_import(
            team=self.team,
            user=self.user,
            integration_id=self.apns.id,
            content="\n".join(["distinct_id,device_token", *lines]).encode(),
            create_missing_persons=create_missing_persons,
        )


class TestPushTokenImportJob(_PushTokenImportTestCase):
    def _on_statement(self, sql_prefix: str, fault: Callable[[], None]) -> Any:
        table = PushTokenImport._meta.db_table
        fired = False

        def wrapper(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
            nonlocal fired
            if not fired and sql.startswith(sql_prefix.format(table=table)):
                fired = True
                fault()
            return execute(sql, params, many, context)

        return connections[router.db_for_write(PushTokenImport)].execute_wrapper(wrapper)

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
        self.queue.advance()

        result = get_push_token_import(self.team.id, started.id)
        assert result.status == PushTokenImportStatus.COMPLETED
        assert self.ingestion.devices() == ["user-1", "user-2", "user-3"]
        assert (result.total_devices, result.imported_devices, result.failed_devices) == (5, 3, 3)
        assert sorted((failure.line, failure.reason) for failure in result.failures) == [
            (4, PushTokenImportRowFailureReason.INVALID_ROW),
            (5, PushTokenImportRowFailureReason.TOKEN_MISMATCH),
            (6, PushTokenImportRowFailureReason.UNKNOWN_PERSON),
        ]
        assert result.unknown_person_devices == 1
        assert result.can_import_unknown_persons is True

    def test_devices_kept_for_unknown_people_are_deleted_once_they_expire(self) -> None:
        import_id = self._upload([f"nobody,{APNS_TOKEN}"]).id
        self.queue.advance(push_token_import.UNKNOWN_PERSON_DEVICES_KEPT_FOR)
        assert get_push_token_import(self.team.id, import_id).can_import_unknown_persons is True

        self.queue.advance(push_token_import.EXPIRY_MARGIN)

        assert get_push_token_import(self.team.id, import_id).can_import_unknown_persons is False
        assert self.storage.objects == {}

    def test_imports_the_devices_of_unknown_people_once_with_new_persons(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"])
        flush_persons_and_events()
        first = self._upload([f"user-1,{APNS_TOKEN}", f"new-1,{APNS_TOKEN}", f"new-2,{'c3' * 32}"])
        self.queue.advance()

        retry = import_unknown_persons(team=self.team, user=self.user, import_id=first.id)
        with self.assertRaises(PushTokenImportInvalid):
            import_unknown_persons(team=self.team, user=self.user, import_id=first.id)
        self.queue.advance()

        result = get_push_token_import(self.team.id, retry.id)
        assert result.create_missing_persons is True
        assert (result.total_devices, result.imported_devices) == (2, 2)
        assert self.ingestion.devices() == ["new-1", "new-2", "user-1"]
        assert get_push_token_import(self.team.id, first.id).can_import_unknown_persons is False
        assert self.storage.objects == {}

    def test_a_channel_runs_one_import_at_a_time_and_a_cancelled_import_stops_sending(self) -> None:
        first = self._upload([f"user-1,{APNS_TOKEN}"], create_missing_persons=True)
        with self.assertRaisesRegex(PushTokenImportInvalid, "already running"):
            self._upload([f"user-2,{APNS_TOKEN}"])

        cancelled = cancel_push_token_import(self.team.id, first.id)
        self.queue.advance()

        result = get_push_token_import(self.team.id, first.id)
        assert (cancelled.status, cancelled.finished_at) == (PushTokenImportStatus.CANCELLED, None)
        assert result.status == PushTokenImportStatus.CANCELLED
        assert result.finished_at is not None
        assert self.ingestion.devices() == []
        assert self.storage.objects == {}
        assert self._upload([f"user-2,{APNS_TOKEN}"]).status == PushTokenImportStatus.RUNNING

    def test_a_stop_that_lands_during_a_batch_still_counts_that_batch(self) -> None:
        import_id = self._upload(THREE_DEVICES, create_missing_persons=True).id

        def stop_while_sending(**kwargs: Any) -> CaptureInternalResult:
            cancel_push_token_import(self.team.id, import_id)
            return self.ingestion.capture(**kwargs)

        with patch("posthog.api.integration_push_tokens.capture_batch_internal", side_effect=stop_while_sending):
            self.queue.advance()

        result = get_push_token_import(self.team.id, import_id)

        assert (result.status, result.processed_devices, result.imported_devices) == (
            PushTokenImportStatus.CANCELLED,
            2,
            2,
        )
        assert result.finished_at is not None
        assert self.storage.objects == {}

    @parameterized.expand([("dropped",), ("unaccounted",)])
    def test_a_device_ingestion_did_not_confirm_is_sent_again_and_stored_once(
        self, failure: Literal["dropped", "unaccounted"]
    ) -> None:
        self.ingestion.fails_once = {"b": failure}
        import_id = self._upload([f"a,{APNS_TOKEN}", f"b,{APNS_TOKEN}"], create_missing_persons=True).id

        self.queue.advance()

        result = get_push_token_import(self.team.id, import_id)
        assert (result.imported_devices, result.failed_devices) == (2, 0)
        assert self.ingestion.devices() == ["a", "b"]

    def test_a_failed_delete_is_tried_again_until_the_devices_are_gone(self) -> None:
        import_id = self._upload([f"a,{APNS_TOKEN}"], create_missing_persons=True).id
        self.storage.down = True
        self.queue.advance()
        assert self.storage.objects != {}

        self.storage.down = False
        self.queue.advance(push_token_import.DELETE_RETRY_AFTER)

        assert self.storage.objects == {}
        assert PushTokenImport.objects.for_team(self.team.id).get(id=import_id).storage_key == ""

    def test_a_batch_sent_again_after_its_worker_died_is_stored_once(self) -> None:
        import_id = self._upload(THREE_DEVICES, create_missing_persons=True).id

        def store_then_die(**kwargs: Any) -> None:
            capture.side_effect = self.ingestion.capture
            self.ingestion.capture(**kwargs)
            raise SystemExit("the worker was killed after ingestion stored the batch")

        with patch("posthog.api.integration_push_tokens.capture_batch_internal", side_effect=store_then_die) as capture:
            self.queue.advance(push_token_import.STALLED_AFTER)

        result = get_push_token_import(self.team.id, import_id)
        assert (result.status, result.imported_devices) == (PushTokenImportStatus.COMPLETED, 3)
        assert self.ingestion.devices() == ["a", "b", "c"]

    def test_an_import_whose_stored_devices_are_gone_fails_instead_of_completing(self) -> None:
        import_id = self._upload([f"a,{APNS_TOKEN}"], create_missing_persons=True).id
        self.storage.objects.clear()

        self.queue.advance()

        result = get_push_token_import(self.team.id, import_id)
        assert result.status == PushTokenImportStatus.FAILED
        assert "couldn't read the stored devices" in result.error
        assert self.ingestion.devices() == []

    def test_a_failed_delete_does_not_let_unknown_people_be_imported_twice(self) -> None:
        first = self._upload([f"new-1,{APNS_TOKEN}"])
        self.queue.advance()
        self.storage.down = True
        import_unknown_persons(team=self.team, user=self.user, import_id=first.id)
        self.queue.advance()

        with self.assertRaises(PushTokenImportInvalid):
            import_unknown_persons(team=self.team, user=self.user, import_id=first.id)

    def test_a_failed_row_write_deletes_the_stored_devices(self) -> None:
        def database_down() -> None:
            raise OperationalError("database down")

        with self._on_statement('INSERT INTO "{table}"', database_down):
            with self.assertRaises(OperationalError):
                self._upload([f"a,{APNS_TOKEN}"])

        assert self.storage.objects == {}

    def test_progress_during_the_last_stall_check_keeps_the_import_running(self) -> None:
        self.queue.loses_imports = True
        import_id = self._upload(THREE_DEVICES, create_missing_persons=True).id

        def worker_comes_back() -> None:
            self.queue.loses_imports = False
            self.queue.run(tasks.run_push_token_import, {"team_id": self.team.id, "import_id": str(import_id)})

        with self._on_statement('UPDATE "{table}" SET "status"', worker_comes_back):
            self.queue.advance(push_token_import.STALLED_AFTER * (push_token_import.MAX_RESUMES + 1))

        assert get_push_token_import(self.team.id, import_id).status == PushTokenImportStatus.COMPLETED
        assert self.ingestion.devices() == ["a", "b", "c"]

    def test_an_import_that_never_progresses_fails_after_its_resumes(self) -> None:
        self.queue.loses_imports = True
        stuck = self._upload([f"d,{APNS_TOKEN}"], create_missing_persons=True)
        self.queue.advance(push_token_import.STALLED_AFTER * (push_token_import.MAX_RESUMES + 1))

        result = get_push_token_import(self.team.id, stuck.id)
        assert result.status == PushTokenImportStatus.FAILED
        assert "stopped after 0 of 1 devices" in result.error
        assert self.storage.objects == {}


class TestPushTokenImportApi(_PushTokenImportTestCase):
    def _post_file(self, lines: list[str], integration_id: int | None = None, **data: Any):
        content = "\n".join(["distinct_id,device_token", *lines]).encode()
        return self.client.post(
            f"/api/projects/{self.team.pk}/push_token_imports/",
            {
                "integration_id": integration_id or self.apns.id,
                "device_token_file": SimpleUploadedFile("devices.csv", content, content_type="text/csv"),
                **data,
            },
            format="multipart",
        )

    def test_uploads_a_file_and_reads_its_result(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"])
        flush_persons_and_events()

        response = self._post_file([f"user-1,{APNS_TOKEN}", f"nobody,{'b2' * 32}"])

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["status"] == "running"
        self.queue.advance()
        url = f"/api/projects/{self.team.pk}/push_token_imports"
        result = self.client.get(f"{url}/{response.json()['id']}/").json()
        assert result["status"] == "completed"
        assert [(failure["line"], failure["reason"]) for failure in result["failures"]] == [(3, "unknown_person")]
        assert result["can_import_unknown_persons"] is True
        latest = self.client.get(f"{url}/latest/", {"integration_id": self.apns.id}).json()
        assert latest["latest"]["id"] == response.json()["id"]

    def test_a_second_import_while_one_runs_is_a_bad_request(self) -> None:
        first = self._post_file([f"user-1,{APNS_TOKEN}"]).json()

        second = self._post_file([f"user-2,{APNS_TOKEN}"])

        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert "already running" in second.json()["detail"]
        cancelled = self.client.post(f"/api/projects/{self.team.pk}/push_token_imports/{first['id']}/cancel/")
        assert (cancelled.json()["status"], cancelled.json()["finished_at"]) == ("cancelled", None)

    def test_importing_unknown_people_twice_is_a_bad_request(self) -> None:
        first = self._post_file([f"new-1,{APNS_TOKEN}"]).json()
        self.queue.advance()
        url = f"/api/projects/{self.team.pk}/push_token_imports/{first['id']}/import_unknown_persons/"

        retry = self.client.post(url)
        again = self.client.post(url)

        assert retry.status_code == status.HTTP_201_CREATED, retry.json()
        assert again.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            (["integration:write"], status.HTTP_403_FORBIDDEN),
            (["integration:write", "person:write"], status.HTTP_201_CREATED),
        ]
    )
    def test_an_api_key_needs_person_access_to_import(self, scopes: list[str], expected: int) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="t", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/push_token_imports/",
            {
                "integration_id": self.apns.id,
                "device_token_file": SimpleUploadedFile("d.csv", f"distinct_id,device_token\na,{APNS_TOKEN}".encode()),
            },
            format="multipart",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, None, status.HTTP_403_FORBIDDEN),
            ("not_a_push_channel", OrganizationMembership.Level.ADMIN, "slack", status.HTTP_400_BAD_REQUEST),
            ("another_team", OrganizationMembership.Level.ADMIN, "other_team", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_refuses_an_upload_into_a_channel_the_user_cannot_change(
        self, _name: str, level: int, channel: str | None, expected: int
    ) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()
        integration_id = self.apns.id
        if channel == "slack":
            integration_id = Integration.objects.create(team=self.team, kind="slack", config={}).id
        if channel == "other_team":
            other_team = Team.objects.create(organization=self.organization)
            integration_id = Integration.objects.create(
                team=other_team, kind="apns", integration_id="x", config={"bundle_id": "com.example.other"}
            ).id

        response = self._post_file([f"user-1,{APNS_TOKEN}"], integration_id=integration_id)

        assert response.status_code == expected, response.json()
        assert PushTokenImport.objects.for_team(self.team.id).count() == 0
        assert self.storage.objects == {}
