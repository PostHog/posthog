import json
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

from .test_suggestions import ingest_one, make_draft

REVIEW_FIELDS = ("reviewed_by_id", "reviewed_at", "dismissal_reason", "dismissal_note", "dismissed_at_score")
FLAG = "products.warehouse_suggestions.backend.presentation.views.is_warehouse_suggestions_enabled"


class TestWarehouseSuggestionAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(FLAG, return_value=True))
        self.url = f"/api/projects/{self.team.id}/warehouse_suggestions"
        self.view = self._make_view("orders")
        self.table = DataWarehouseTable.objects.create(
            team=self.team,
            name="stripe_charges",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://bucket/stripe_charges",
        )

    def _make_view(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )

    def _materialize(self, view: DataWarehouseSavedQuery) -> DataWarehouseTable:
        backing_table = DataWarehouseTable.objects.create(
            team=self.team,
            name=view.name,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=f"s3://bucket/{view.folder_path}/{view.normalized_name}",
        )
        DataWarehouseSavedQuery.objects.filter(id=view.id).update(table=backing_table, is_materialized=True)
        return backing_table

    def _suggest(
        self,
        subject_id: UUID,
        *,
        subject_kind: WarehouseSuggestionSubjectKind = WarehouseSuggestionSubjectKind.SAVED_QUERY,
        score: float = 1.0,
    ) -> WarehouseSuggestion:
        return ingest_one(
            self.team.id,
            make_draft(
                fingerprint=f"certify:{subject_id}", subject_kind=subject_kind, subject_id=subject_id, score=score
            ),
        )

    def _restrict(self, resource: str, resource_id: UUID | None, access_level: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=str(resource_id) if resource_id else None,
            organization_member=self.organization_membership,
            access_level=access_level,
        )

    def test_list_dismiss_and_resume(self) -> None:
        low = self._suggest(self.view.id, score=2.0)
        high = self._suggest(self.table.id, subject_kind=WarehouseSuggestionSubjectKind.TABLE, score=9.0)

        listed = self.client.get(f"{self.url}/")
        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert [row["id"] for row in listed.json()["results"]] == [str(high.id), str(low.id)]
        assert all(row["can_act"] for row in listed.json()["results"])

        dismissed = self.client.post(
            f"{self.url}/{low.id}/dismiss/",
            {"reason": WarehouseSuggestionDismissalReason.OTHER, "note": "We sunset this view"},
        )
        assert dismissed.status_code == status.HTTP_200_OK, dismissed.json()
        low.refresh_from_db()
        assert low.status == WarehouseSuggestionStatus.DISMISSED
        assert low.reviewed_by_id == self.user.id
        assert low.reviewed_at is not None
        assert low.dismissal_reason == WarehouseSuggestionDismissalReason.OTHER
        assert low.dismissal_note == "We sunset this view"
        assert low.dismissed_at_score == 2.0

        resumed = self.client.post(f"{self.url}/{low.id}/resume/")
        assert resumed.status_code == status.HTTP_200_OK, resumed.json()
        low.refresh_from_db()
        assert low.status == WarehouseSuggestionStatus.PROPOSED
        assert {field: getattr(low, field) for field in REVIEW_FIELDS} == dict.fromkeys(REVIEW_FIELDS)
        logged = ActivityLog.objects.filter(team_id=self.team.id, scope="WarehouseSuggestion", item_id=str(low.id))
        assert logged.count() == 2
        assert "We sunset this view" not in json.dumps([entry.detail for entry in logged], default=str)

    @parameterized.expand(
        [
            ("dismiss_a_dismissed_one", WarehouseSuggestionStatus.DISMISSED, "dismiss"),
            ("resume_an_expired_one", WarehouseSuggestionStatus.EXPIRED, "resume"),
        ]
    )
    def test_a_move_people_may_not_make_conflicts(
        self, _name: str, current: WarehouseSuggestionStatus, action: str
    ) -> None:
        suggestion = self._suggest(self.view.id)
        WarehouseSuggestion.objects.for_team(self.team.id).filter(id=suggestion.id).update(status=current)

        response = self.client.post(
            f"{self.url}/{suggestion.id}/{action}/", {"reason": WarehouseSuggestionDismissalReason.NOT_NOW}
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()

    @parameterized.expand(
        [
            ("by_kind", "kind=deprecate", status.HTTP_200_OK, ["table"]),
            ("by_status", "status=dismissed", status.HTTP_200_OK, ["table"]),
            ("by_kind_and_status", "kind=certify&status=dismissed", status.HTTP_200_OK, []),
            ("unknown_status", "status=bogus", status.HTTP_400_BAD_REQUEST, None),
        ]
    )
    def test_list_filters(self, _name: str, query: str, expected_status: int, expected: list[str] | None) -> None:
        ids = {
            "view": self._suggest(self.view.id).id,
            "table": self._suggest(self.table.id, subject_kind=WarehouseSuggestionSubjectKind.TABLE).id,
        }
        WarehouseSuggestion.objects.for_team(self.team.id).filter(id=ids["table"]).update(
            kind=WarehouseSuggestionKind.DEPRECATE, status=WarehouseSuggestionStatus.DISMISSED
        )

        response = self.client.get(f"{self.url}/?{query}")

        assert response.status_code == expected_status, response.json()
        if expected is not None:
            assert response.json()["count"] == len(expected)
            assert [row["id"] for row in response.json()["results"]] == [str(ids[name]) for name in expected]

    def test_the_flag_off_forbids_the_endpoint(self) -> None:
        with patch(FLAG, return_value=False):
            response = self.client.get(f"{self.url}/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_a_member_sees_nothing_about_subjects_they_cannot_read(self) -> None:
        visible = self._suggest(self.table.id, subject_kind=WarehouseSuggestionSubjectKind.TABLE)
        denied_view = self._suggest(self.view.id)
        deleted_view = self._make_view("old_orders")
        about_deleted = self._suggest(deleted_view.id)
        DataWarehouseSavedQuery.objects.filter(id=deleted_view.id).update(deleted=True)
        about_backing_table = self._suggest(
            self._materialize(self.view).id, subject_kind=WarehouseSuggestionSubjectKind.TABLE
        )
        self._restrict("warehouse_view", self.view.id, "none")

        listed = self.client.get(f"{self.url}/")

        assert listed.json()["count"] == 1
        assert [row["id"] for row in listed.json()["results"]] == [str(visible.id)]
        for hidden in (denied_view, about_deleted, about_backing_table):
            assert self.client.get(f"{self.url}/{hidden.id}/").status_code == status.HTTP_404_NOT_FOUND
            for action in ("dismiss", "resume"):
                response = self.client.post(
                    f"{self.url}/{hidden.id}/{action}/", {"reason": WarehouseSuggestionDismissalReason.NOT_NOW}
                )
                assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("warehouse_viewer_with_edit_on_the_view", "viewer", "editor", status.HTTP_200_OK),
            ("no_warehouse_access_with_view_on_the_view", "none", "viewer", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_a_grant_on_one_view_is_enough(
        self, _name: str, warehouse_level: str, view_level: str, expected_dismiss_status: int
    ) -> None:
        suggestion = self._suggest(self.view.id)
        self._restrict("warehouse_objects", None, warehouse_level)
        self._restrict("warehouse_view", self.view.id, view_level)

        listed = self.client.get(f"{self.url}/")
        dismissed = self.client.post(
            f"{self.url}/{suggestion.id}/dismiss/", {"reason": WarehouseSuggestionDismissalReason.NOT_NOW}
        )

        assert [row["id"] for row in listed.json()["results"]] == [str(suggestion.id)]
        assert dismissed.status_code == expected_dismiss_status, dismissed.json()

    def test_a_viewer_of_the_subject_cannot_dismiss_its_suggestion(self) -> None:
        suggestion = self._suggest(self.view.id)
        self._restrict("warehouse_view", self.view.id, "viewer")

        listed = self.client.get(f"{self.url}/")
        dismissed = self.client.post(
            f"{self.url}/{suggestion.id}/dismiss/", {"reason": WarehouseSuggestionDismissalReason.NOT_USEFUL}
        )

        assert listed.json()["results"][0]["can_act"] is False
        assert dismissed.status_code == status.HTTP_403_FORBIDDEN, dismissed.json()
        suggestion.refresh_from_db()
        assert suggestion.status == WarehouseSuggestionStatus.PROPOSED

    def test_pages_do_not_overlap_or_skip_rows_at_the_boundary(self) -> None:
        suggestions = [self._suggest(self._make_view(f"view_{index}").id, score=1.0) for index in range(5)]

        pages = [self.client.get(f"{self.url}/?limit=2&offset={offset}").json() for offset in (0, 2, 4)]

        assert [page["count"] for page in pages] == [5, 5, 5]
        assert [len(page["results"]) for page in pages] == [2, 2, 1]
        listed = [row["id"] for page in pages for row in page["results"]]
        assert listed == [str(row.id) for row in sorted(suggestions, key=lambda row: row.id)]

    def test_listing_runs_a_constant_number_of_queries(self) -> None:
        def count_list_queries() -> int:
            WarehouseSuggestion.objects.for_team(self.team.id).update(reviewed_by=self.user)
            with CaptureQueriesContext(connection) as queries:
                assert self.client.get(f"{self.url}/").status_code == status.HTTP_200_OK
            return len(queries)

        self._suggest(self.view.id)
        count_list_queries()
        one_row = count_list_queries()
        for index in range(4):
            self._suggest(self._make_view(f"view_{index}").id)

        assert count_list_queries() == one_row
