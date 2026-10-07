from dataclasses import replace
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.data_catalog.backend.facade.api import certifications_for_team, propose_certification
from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Node, NodeType
from products.warehouse_suggestions.backend.facade.contracts import (
    CertifyPayload,
    DeprecatePayload,
    MaterializePayload,
    SuggestionPayload,
)
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

from .test_api import ingest_surfaced
from .test_suggestions import make_draft

FLAG = "products.warehouse_suggestions.backend.presentation.views.is_warehouse_suggestions_enabled"
DAY_SECONDS = 24 * 60 * 60
REPORT = "products.warehouse_suggestions.backend.logic.analytics.report_user_or_team_action"
PAYLOADS: dict[WarehouseSuggestionKind, SuggestionPayload] = {
    WarehouseSuggestionKind.CERTIFY: CertifyPayload(subject_name="orders"),
    WarehouseSuggestionKind.DEPRECATE: DeprecatePayload(
        subject_name="orders", refresh_seconds_per_month=0, refresh_bytes_per_month=0
    ),
    WarehouseSuggestionKind.MATERIALIZE: MaterializePayload(
        subject_name="orders",
        refresh_interval_seconds=DAY_SECONDS,
        saves_seconds_per_month=900,
        saves_bytes_per_month=0,
        freshness_today_seconds=None,
        freshness_after_seconds=DAY_SECONDS,
        live_sources=(),
        unknown_sources=(),
    ),
}


class TestAcceptSuggestion(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(FLAG, return_value=True))
        self.enterContext(patch.object(DataWarehouseSavedQuery, "schedule_materialization"))
        self.url = f"/api/projects/{self.team.id}/warehouse_suggestions"
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="orders",
            query={"kind": "HogQLQuery", "query": "SELECT timestamp, event FROM events"},
            created_by=self.user,
        )
        Node.objects.create(
            team=self.team,
            dag=DAG.objects.create(team=self.team, name=f"posthog_{self.team.id}"),
            name="orders",
            saved_query=self.view,
            type=NodeType.VIEW,
        )

    def _suggest(self, kind: WarehouseSuggestionKind) -> WarehouseSuggestion:
        draft = make_draft(fingerprint=f"{kind}:orders", subject_id=self.view.id)
        return ingest_surfaced(self.team.id, replace(draft, kind=kind, payload=PAYLOADS[kind]))

    def _accept(self, suggestion_id: UUID, body: dict | None = None) -> dict:
        response = self.client.post(f"{self.url}/{suggestion_id}/accept/", body or {})
        return {**response.json(), "http_status": response.status_code}

    def _certification_status(self) -> str | None:
        certification = certifications_for_team(self.team).filter(saved_query_id=self.view.id).first()
        return certification.status if certification else None

    @parameterized.expand(
        [
            ("certify", WarehouseSuggestionKind.CERTIFY, CertificationStatus.CERTIFIED),
            ("deprecate", WarehouseSuggestionKind.DEPRECATE, CertificationStatus.DEPRECATED),
        ]
    )
    def test_accepting_a_catalog_suggestion_sets_the_certification_once(
        self, _name: str, kind: WarehouseSuggestionKind, expected: CertificationStatus
    ) -> None:
        suggestion = self._suggest(kind)

        first = self._accept(suggestion.id)
        second = self._accept(suggestion.id)

        assert (first["http_status"], second["http_status"]) == (status.HTTP_200_OK, status.HTTP_200_OK), first
        assert second["created_asset"] == first["created_asset"] is not None
        assert self._certification_status() == expected
        assert ActivityLog.objects.filter(
            team_id=self.team.id, scope="WarehouseSuggestion", item_id=str(suggestion.id), activity="updated"
        ).exists()

    def test_accepting_twice_reports_one_acceptance(self) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.CERTIFY)

        with patch(REPORT) as report:
            self._accept(suggestion.id)
            self._accept(suggestion.id)

        assert [call.args[0] for call in report.call_args_list] == ["warehouse suggestion accepted"]

    def test_deprecating_a_certified_view_reuses_its_certification(self) -> None:
        certification = propose_certification(team=self.team, user=self.user, saved_query_id=self.view.id)
        suggestion = self._suggest(WarehouseSuggestionKind.DEPRECATE)

        accepted = self._accept(suggestion.id)

        assert accepted["created_asset"] == {"certification_id": str(certification.id)}
        assert self._certification_status() == CertificationStatus.DEPRECATED

    def test_accepting_a_materialize_suggestion_materializes_the_view_on_the_chosen_interval(self) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.MATERIALIZE)

        accepted = self._accept(suggestion.id, {"refresh_interval_seconds": 12 * 60 * 60})

        self.view.refresh_from_db()
        assert accepted["http_status"] == status.HTTP_200_OK, accepted
        assert (self.view.is_materialized, accepted["created_asset"]["refresh_interval_seconds"]) == (
            True,
            12 * 60 * 60,
        )

    def test_a_refused_interval_is_a_field_error_and_keeps_the_suggestion_open(self) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.MATERIALIZE)

        refused = self._accept(suggestion.id, {"refresh_interval_seconds": 7})

        suggestion.refresh_from_db()
        assert (refused["http_status"], refused["attr"]) == (status.HTTP_400_BAD_REQUEST, "refresh_interval_seconds")
        assert suggestion.status == WarehouseSuggestionStatus.PROPOSED

    def test_a_view_deleted_after_the_suggestion_was_loaded_is_auto_resolved(self) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.CERTIFY)

        with patch("products.warehouse_suggestions.backend.logic.accept.get_saved_query_summary", return_value=None):
            gone = self._accept(suggestion.id)

        assert (gone["http_status"], gone["attr"]) == (status.HTTP_400_BAD_REQUEST, "subject_id")
        assert WarehouseSuggestion.objects.for_team(self.team.id).get(id=suggestion.id).status == (
            WarehouseSuggestionStatus.AUTO_RESOLVED
        )
