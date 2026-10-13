import json
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.services import people_import
from products.workflows.backend.services.people_import import PeopleImportInvalid, start_people_import
from products.workflows.backend.tasks import people_import as people_import_tasks
from products.workflows.backend.tasks.people_import import capture_people_import, fill_people_import_cohort


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

    def stored_people(self) -> list[dict[str, Any]]:
        [content] = self.storage.objects.values()
        return json.loads(content)


class TestPeopleImport(_StorageMixin, ClickhouseTestMixin, BaseTest):
    def test_each_row_writes_to_the_right_person(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"], properties={"email": "ada@example.com"})
        _create_person(team=self.team, distinct_ids=["b-newer"], properties={"email": "grace@example.com"})
        flush_persons_and_events()
        rows: list[dict[str, str]] = [
            {"Email": "ada@example.com", "Distinct ID": "user-1", "Plan": "Pro"},
            {"Email": "Grace@Example.com", "Plan": "Free"},
            {"Email": "new@example.com", "Distinct ID": "user-9", "Plan": "Team"},
            {"Email": "lead@example.com", "Plan": "Trial"},
            {"Email": "not-an-email", "Plan": "Free"},
            {"Email": "LEAD@example.com", "Plan": "Duplicate"},
            {"Email": "big@example.com", "Plan": "x" * 5000},
            {"Email": "other@example.com", "Distinct ID": "user-1", "Plan": "Same person twice"},
        ]

        summary = start_people_import(team=self.team, user=self.user, name="Spring sale", rows=rows)

        assert [(p["distinct_id"], p["properties"]) for p in self.stored_people()] == [
            ("user-1", {"email": "ada@example.com", "plan": "Pro"}),
            ("b-newer", {"email": "Grace@Example.com", "plan": "Free"}),
            ("user-9", {"email": "new@example.com", "plan": "Team"}),
            ("lead@example.com", {"email": "lead@example.com", "plan": "Trial"}),
        ]
        assert (summary.row_count, summary.new_people, summary.columns) == (4, 2, ["email", "plan"])
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
            ("no_email_column", [{"name": "Ada"}], 'column named "email"'),
            ("no_valid_email", [{"email": "nope"}], "No row has a valid email"),
            ("non_ascii_header", [{"email": "a@example.com", "会社": "Hedgebox"}], 'column "会社" needs a name'),
            (
                "two_columns_with_one_name",
                [{"email": "a@example.com", "Email ": "b@example.com"}],
                'both named "email"',
            ),
        ]
    )
    def test_rejects_unusable_files(self, _name: str, rows: list[dict[str, str]], message: str) -> None:
        with self.assertRaises(PeopleImportInvalid) as error:
            start_people_import(team=self.team, user=self.user, name="List", rows=rows)
        assert message in str(error.exception)
        assert not Cohort.objects.filter(team_id=self.team.id).exists()


class TestPeopleImportTasks(_StorageMixin, BaseTest):
    def _stage(self) -> tuple[int, str]:
        cohort = Cohort.objects.create(team=self.team, name="List", is_static=True, is_calculating=True)
        key = f"workflows_people_imports/team-{self.team.id}/{cohort.pk}.json"
        self.storage.write(key, json.dumps([{"distinct_id": "user-1", "properties": {"email": "a@example.com"}}]))
        return cohort.pk, key

    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    @patch("products.workflows.backend.tasks.people_import.capture_batch_internal")
    def test_capture_sets_each_row_on_its_person(self, capture: MagicMock, fill: MagicMock) -> None:
        cohort_id, key = self._stage()
        capture.return_value.succeeded.return_value = True

        capture_people_import(team_id=self.team.id, cohort_id=cohort_id, storage_key=key)

        [event] = capture.call_args.kwargs["events"]
        assert (event["event"], event["distinct_id"], event["properties"]) == (
            "$set",
            "user-1",
            {"$set": {"email": "a@example.com"}},
        )
        assert capture.call_args.kwargs["process_person_profile"] is True
        fill.assert_called_once()

    @parameterized.expand([("still_missing", {}, True), ("all_found", {"user-1": object()}, False)])
    @patch("products.workflows.backend.tasks.people_import.calculate_cohort_from_list.delay")
    @patch("products.workflows.backend.tasks.people_import.fill_people_import_cohort.apply_async")
    def test_fill_waits_for_ingestion(
        self, _name: str, found: dict, waits: bool, reschedule: MagicMock, calculate: MagicMock
    ) -> None:
        cohort_id, key = self._stage()

        with patch.object(people_import_tasks, "get_persons_mapped_by_distinct_id", return_value=found):
            fill_people_import_cohort(team_id=self.team.id, cohort_id=cohort_id, storage_key=key, attempt=0)

        assert reschedule.called is waits
        assert calculate.called is not waits
        assert (key in self.storage.objects) is waits


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
