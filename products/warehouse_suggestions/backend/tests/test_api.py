from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionDismissalReason,
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

    def _restrict(self, resource: str, resource_id: UUID, access_level: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=str(resource_id),
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

    def test_deciding_a_decided_suggestion_conflicts(self) -> None:
        suggestion = self._suggest(self.view.id)
        self.client.post(f"{self.url}/{suggestion.id}/dismiss/", {"reason": WarehouseSuggestionDismissalReason.NOT_NOW})

        again = self.client.post(
            f"{self.url}/{suggestion.id}/dismiss/", {"reason": WarehouseSuggestionDismissalReason.NOT_NOW}
        )

        assert again.status_code == status.HTTP_409_CONFLICT, again.json()

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
        self._restrict("warehouse_view", self.view.id, "none")

        listed = self.client.get(f"{self.url}/")

        assert listed.json()["count"] == 1
        assert [row["id"] for row in listed.json()["results"]] == [str(visible.id)]
        for hidden in (denied_view, about_deleted):
            assert self.client.get(f"{self.url}/{hidden.id}/").status_code == status.HTTP_404_NOT_FOUND

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
