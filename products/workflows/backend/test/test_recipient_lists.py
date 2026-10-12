from datetime import timedelta
from typing import Any
from uuid import UUID

import time_machine
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized
from rest_framework import status

from posthog.api.capture import CaptureInternalResult
from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey, PropertyDefinition
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.facade.contracts import RecipientListInvalid
from products.workflows.backend.models.recipient_list import RecipientList, RecipientListRow
from products.workflows.backend.services import recipient_lists
from products.workflows.backend.services.recipient_lists import start_recipient_list_import
from products.workflows.backend.tasks import recipient_lists as recipient_list_tasks
from products.workflows.backend.tasks.recipient_lists import (
    capture_recipient_list_people,
    delete_expired_recipient_lists,
    fail_stalled_recipient_list_import_tasks,
    fill_recipient_list_cohort,
)


class _DispatchMixin:
    team: Any

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        dispatch = patch("products.workflows.backend.tasks.recipient_lists.capture_recipient_list_people.delay")
        self.dispatch = dispatch.start()
        self.addCleanup(dispatch.stop)  # type: ignore[attr-defined]

    def stored_rows(self, recipient_list_id: UUID) -> list[tuple[str, dict[str, str]]]:
        rows = RecipientListRow.objects.for_team(self.team.id).filter(recipient_list_id=recipient_list_id)
        return [(row.distinct_id, row.data) for row in rows.order_by("id")]


class TestRecipientListImport(_DispatchMixin, ClickhouseTestMixin, BaseTest):
    def test_each_row_belongs_to_the_right_person(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"], properties={"email": "ada@example.com"})
        _create_person(team=self.team, distinct_ids=["b-newer"], properties={"email": "grace@example.com"})
        flush_persons_and_events()
        rows: list[dict[str, str]] = [
            {"Email": "ada@example.com", "Distinct ID": "user-1", "subscriptionPlan": "Pro", " ": ""},
            {"Email": "Grace@Example.com", "subscriptionPlan": "Free"},
            {"Email": "new@example.com", "Distinct ID": "user-9", "subscriptionPlan": "Team"},
            {"Email": "lead@example.com", "subscriptionPlan": "Trial"},
            {"Email": "not-an-email", "subscriptionPlan": "Free"},
            {"Email": "LEAD@example.com", "subscriptionPlan": "Duplicate"},
            {"Email": "big@example.com", "subscriptionPlan": "x" * 5000},
            {"Email": "other@example.com", "Distinct ID": "user-1", "subscriptionPlan": "Same person twice"},
        ]

        summary = start_recipient_list_import(team=self.team, user=self.user, name="Spring sale", rows=rows)

        assert self.stored_rows(summary.id) == [
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
        summary = start_recipient_list_import(team=self.team, user=self.user, name="List", rows=[row])

        assert self.stored_rows(summary.id) == [expected]

    @parameterized.expand(
        [
            ("no_email_column", [{"name": "Ada"}], 'column named "email"', False),
            ("no_valid_email", [{"email": "nope"}], "No row has a valid email", False),
            (
                "illegal_distinct_id",
                [{"email": "a@example.com", "distinct_id": "Anonymous"}],
                'Row 2 has the distinct_id "Anonymous"',
                False,
            ),
            (
                "long_distinct_id",
                [{"email": "a@example.com", "distinct_id": "x" * 201}],
                "longer than 200 bytes",
                False,
            ),
            ("blank_header_with_data", [{"email": "a@example.com", "   ": "Hedgebox"}], "has no name", False),
            (
                "two_columns_with_one_name",
                [{"email": "a@example.com", "Email ": "b@example.com"}],
                'both named "email"',
                False,
            ),
            ("new_person_with_read_only_email", [{"email": "a@example.com", "plan": "Pro"}], "can't change", True),
        ]
    )
    def test_rejects_unusable_files(
        self, _name: str, rows: list[dict[str, str]], message: str, email_read_only: bool
    ) -> None:
        if email_read_only:
            self.organization.available_product_features = [
                {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
            ]
            self.organization.save(update_fields=["available_product_features"])
            PropertyAccessControl.objects.create(
                team=self.team,
                property_definition=PropertyDefinition.objects.create(
                    team=self.team, name="email", property_type="String", type=PropertyDefinition.Type.PERSON
                ),
                access_level=PropertyAccessLevel.READ.value,
            )
        with self.assertRaises(RecipientListInvalid) as error:
            start_recipient_list_import(team=self.team, user=self.user, name="List", rows=rows)
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

        summary = start_recipient_list_import(
            team=self.team, user=self.user, name="List", rows=[{"email": "ada@example.com"}]
        )

        assert [distinct_id for distinct_id, _ in self.stored_rows(summary.id)] == ["user-1"]

    def test_ends_the_import_when_dispatch_fails(self) -> None:
        self.dispatch.side_effect = ConnectionError("broker is down")

        with self.assertRaises(ConnectionError):
            start_recipient_list_import(team=self.team, user=self.user, name="List", rows=[{"email": "a@example.com"}])

        cohort = Cohort.objects.get(team_id=self.team.id)
        assert (cohort.is_calculating, cohort.errors_calculating) == (False, 1)
        assert not RecipientList.objects.for_team(self.team.id).exists()


@patch.object(recipient_lists, "get_person_uuids_and_matched_distinct_ids", return_value=([], set()))
class TestRecipientListTasks(BaseTest):
    def _stage(self, distinct_ids: tuple[str, ...] = ("user-1",)) -> tuple[int, str]:
        cohort = Cohort.objects.create(team=self.team, name="List", is_static=True, is_calculating=True)
        recipient_list = RecipientList.objects.for_team(self.team.id).create(team=self.team, cohort_id=cohort.pk)
        for distinct_id in distinct_ids:
            RecipientListRow.objects.for_team(self.team.id).create(
                team=self.team,
                recipient_list=recipient_list,
                distinct_id=distinct_id,
                data={"email": f"{distinct_id}@example.com", "plan": "Pro"},
            )
        return cohort.pk, str(recipient_list.id)

    @parameterized.expand(
        [
            ("one_new_person", {"user-1"}, ["user-2"], None),
            ("no_new_people", {"user-1", "user-2"}, None, 0),
        ]
    )
    @patch("products.workflows.backend.tasks.recipient_lists.fill_recipient_list_cohort.apply_async")
    @patch("products.workflows.backend.tasks.recipient_lists.capture_batch_internal")
    def test_capture_creates_only_new_people_with_just_their_email(
        self,
        _name: str,
        existing: set[str],
        sent: list[str] | None,
        fill_countdown: int | None,
        capture: MagicMock,
        fill: MagicMock,
        lookup: MagicMock,
    ) -> None:
        _, list_id = self._stage(("user-1", "user-2"))
        lookup.return_value = ([], existing)
        capture.return_value.succeeded.return_value = True

        capture_recipient_list_people(team_id=self.team.id, recipient_list_id=list_id)

        if sent is None:
            capture.assert_not_called()
        else:
            assert [(e["event"], e["distinct_id"], e["properties"]) for e in capture.call_args.kwargs["events"]] == [
                ("$set", "user-2", {"$set": {"email": "user-2@example.com"}, "$geoip_disable": True})
            ]
            assert capture.call_args.kwargs["process_person_profile"] is True
        assert fill.call_args.kwargs["countdown"] == (fill_countdown if fill_countdown is not None else 15)

    @parameterized.expand([("capture_raises", ConnectionError("capture is down")), ("capture_acks_nothing", None)])
    @patch("products.workflows.backend.tasks.recipient_lists.fill_recipient_list_cohort.apply_async")
    @patch("products.workflows.backend.tasks.recipient_lists.capture_batch_internal")
    def test_capture_closes_the_import_after_the_last_retry(
        self, _name: str, error: Exception | None, capture: MagicMock, fill: MagicMock, _lookup: MagicMock
    ) -> None:
        cohort_id, list_id = self._stage()
        capture.side_effect = error or (
            lambda events, **_: CaptureInternalResult(status_code=503, unaccounted=[e["event_uuid"] for e in events])
        )

        capture_recipient_list_people.apply(
            kwargs={"team_id": self.team.id, "recipient_list_id": list_id},
            retries=recipient_list_tasks.CAPTURE_MAX_RETRIES,
        )

        cohort = Cohort.objects.get(pk=cohort_id)
        assert (cohort.is_calculating, cohort.errors_calculating) == (False, 1)
        assert not RecipientList.objects.for_team(self.team.id).exists()
        fill.assert_not_called()

    @parameterized.expand(
        [
            ("partial_ack", None, {"ok": ["user-1"], "retried": ["user-2"]}, ["user-1", "user-2"], ["user-2"]),
            ("dropped_only", None, {"ok": ["user-1"], "dropped": ["user-2"]}, ["user-1", "user-2"], None),
            ("retry_of_a_subset", ["user-2"], {"ok": ["user-2"]}, ["user-2"], None),
        ]
    )
    @patch("products.workflows.backend.tasks.recipient_lists.fill_recipient_list_cohort.apply_async")
    @patch("products.workflows.backend.tasks.recipient_lists.capture_batch_internal")
    def test_capture_resends_only_unacknowledged_events(
        self,
        _name: str,
        pending: list[str] | None,
        buckets: dict[str, list[str]],
        sent: list[str],
        retried: list[str] | None,
        capture: MagicMock,
        fill: MagicMock,
        _lookup: MagicMock,
    ) -> None:
        _, list_id = self._stage(("user-1", "user-2"))

        def submit(events: list[dict], **_: object) -> CaptureInternalResult:
            uuid_of = {event["distinct_id"]: event["event_uuid"] for event in events}

            def uuids(bucket: str) -> list[str]:
                return [uuid_of[distinct_id] for distinct_id in buckets.get(bucket, [])]

            return CaptureInternalResult(
                status_code=200, ok=uuids("ok"), dropped=uuids("dropped"), retried=uuids("retried")
            )

        capture.side_effect = submit
        with patch.object(capture_recipient_list_people, "retry", return_value=Retry()) as retry:
            try:
                capture_recipient_list_people(
                    team_id=self.team.id, recipient_list_id=list_id, pending_distinct_ids=pending
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
    @patch("products.workflows.backend.tasks.recipient_lists.calculate_cohort_from_list.delay")
    @patch("products.workflows.backend.tasks.recipient_lists.fill_recipient_list_cohort.apply_async")
    def test_fill_waits_for_ingestion(
        self,
        _name: str,
        lookup_result: tuple[list[str], set[str]] | Exception,
        attempt: int,
        outcome: str,
        reschedule: MagicMock,
        calculate: MagicMock,
        lookup: MagicMock,
    ) -> None:
        cohort_id, list_id = self._stage()
        lookup.side_effect = [lookup_result]

        fill_recipient_list_cohort(team_id=self.team.id, recipient_list_id=list_id, attempt=attempt)

        cohort = Cohort.objects.get(pk=cohort_id)
        assert reschedule.called is (outcome == "waits")
        assert calculate.called is (outcome == "fills")
        assert RecipientList.objects.for_team(self.team.id).exists() is (outcome != "fails")
        assert cohort.is_calculating is (outcome != "fails")


class TestRecipientListAPI(_DispatchMixin, ClickhouseTestMixin, APIBaseTest):
    def test_upload_returns_its_list_and_rejects_an_unusable_file(self) -> None:
        url = f"/api/projects/{self.team.id}/workflow_recipient_lists/"

        created = self.client.post(
            url, {"name": "List", "rows": [{"email": "a@example.com", "org": "Acme"}]}, format="json"
        )
        rejected = self.client.post(url, {"name": "List", "rows": [{"name": "Ada"}]}, format="json")

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        assert created.json()["columns"] == ["email", "org"]
        assert rejected.status_code == status.HTTP_400_BAD_REQUEST
        found = self.client.get(url, {"cohort_ids": f"{created.json()['cohort_id']},999999"})
        assert found.json() == [
            {"id": created.json()["id"], "cohort_id": created.json()["cohort_id"], "columns": ["email", "org"]}
        ]

    @parameterized.expand([("person_viewer", "viewer", 403), ("person_editor", "editor", 201)])
    def test_upload_needs_person_edit_access(self, _name: str, person_access: str, expected_status: int) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(team=self.team, resource="person", resource_id=None, access_level=person_access)

        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_recipient_lists/",
            {"name": "List", "rows": [{"email": "a@example.com"}]},
            format="json",
        )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [("cohort_only", ["cohort:write"], 403), ("cohort_and_person", ["cohort:write", "person:write"], 201)]
    )
    def test_upload_needs_person_write_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="t", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_recipient_lists/",
            {"name": "List", "rows": [{"email": "a@example.com"}]},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == expected_status, response.json()


class TestRecipientListBroadcasts(APIBaseTest):
    def _list(self, name: str, rows: dict[str, dict[str, str]]) -> int:
        cohort = Cohort.objects.create(team=self.team, name=name, is_static=True)
        recipient_list = RecipientList.objects.for_team(self.team.id).create(
            team=self.team, cohort_id=cohort.pk, columns=["email", "plan"]
        )
        for distinct_id, data in rows.items():
            RecipientListRow.objects.for_team(self.team.id).create(
                team=self.team, recipient_list=recipient_list, distinct_id=distinct_id, data=data
            )
        return cohort.pk

    @parameterized.expand(
        [
            ("soft_deleted_six_days_ago", "soft", 6, True),
            ("soft_deleted_eight_days_ago", "soft", 8, False),
            ("restored_after_a_soft_delete", "restore", 8, True),
            ("hard_deleted", "hard", 0, False),
        ]
    )
    def test_list_goes_a_week_after_its_cohort_is_deleted(
        self, _name: str, deletion: str, days_later: int, kept: bool
    ) -> None:
        cohort = Cohort.objects.get(pk=self._list("Spring sale", {"user-1": {"email": "a@example.com"}}))

        with self.captureOnCommitCallbacks(execute=True):
            if deletion == "hard":
                cohort.delete()
            else:
                cohort.deleted = True
                cohort.save()
        if deletion == "restore":
            with self.captureOnCommitCallbacks(execute=True):
                cohort.deleted = False
                cohort.save()
        with time_machine.travel(timezone.now() + timedelta(days=days_later), tick=False):
            delete_expired_recipient_lists()

        assert RecipientList.objects.for_team(self.team.id).exists() is kept
        assert RecipientListRow.objects.for_team(self.team.id).exists() is kept

    @parameterized.expand(
        [
            ("stalled_for_two_hours", 2.0, True, True),
            ("still_within_the_hour", 0.5, True, False),
            ("finished", 2.0, False, False),
        ]
    )
    def test_sweep_fails_imports_that_stalled(
        self, _name: str, hours_ago: float, calculating: bool, failed: bool
    ) -> None:
        with time_machine.travel(timezone.now() - timedelta(hours=hours_ago), tick=False):
            cohort_id = self._list("Spring sale", {"user-1": {"email": "a@example.com"}})
        Cohort.objects.filter(pk=cohort_id).update(is_calculating=calculating)

        fail_stalled_recipient_list_import_tasks()

        cohort = Cohort.objects.get(pk=cohort_id)
        assert (cohort.errors_calculating, RecipientList.objects.for_team(self.team.id).exists()) == (
            (1, False) if failed else (0, True)
        )
