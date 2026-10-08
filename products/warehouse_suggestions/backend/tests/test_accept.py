from dataclasses import replace
from uuid import UUID

from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team, User
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


def create_view_in_dag(team: Team, user: User) -> DataWarehouseSavedQuery:
    view = DataWarehouseSavedQuery.objects.create(
        team=team,
        name="orders",
        query={"kind": "HogQLQuery", "query": "SELECT timestamp, event FROM events"},
        created_by=user,
    )
    Node.objects.create(
        team=team,
        dag=DAG.objects.create(team=team, name=f"posthog_{team.id}"),
        name="orders",
        saved_query=view,
        type=NodeType.VIEW,
    )
    return view


def suggest(team_id: int, view_id: UUID, kind: WarehouseSuggestionKind) -> WarehouseSuggestion:
    draft = make_draft(fingerprint=f"{kind}:orders", subject_id=view_id)
    return ingest_surfaced(team_id, replace(draft, kind=kind, payload=PAYLOADS[kind]))


class TestAcceptSuggestion(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(FLAG, return_value=True))
        self.enterContext(patch.object(DataWarehouseSavedQuery, "schedule_materialization"))
        self.url = f"/api/projects/{self.team.id}/warehouse_suggestions"
        self.view = create_view_in_dag(self.team, self.user)

    def _suggest(self, kind: WarehouseSuggestionKind) -> WarehouseSuggestion:
        return suggest(self.team.id, self.view.id, kind)

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

    @parameterized.expand(
        [
            (
                "deprecate_reuses_it",
                WarehouseSuggestionKind.DEPRECATE,
                status.HTTP_200_OK,
                WarehouseSuggestionStatus.ACCEPTED,
                CertificationStatus.DEPRECATED,
            ),
            (
                "certify_leaves_it_alone",
                WarehouseSuggestionKind.CERTIFY,
                status.HTTP_409_CONFLICT,
                WarehouseSuggestionStatus.AUTO_RESOLVED,
                CertificationStatus.PROPOSED,
            ),
        ]
    )
    def test_accepting_over_an_existing_certification(
        self,
        _name: str,
        kind: WarehouseSuggestionKind,
        expected_http_status: int,
        expected_suggestion_status: WarehouseSuggestionStatus,
        expected_certification_status: CertificationStatus,
    ) -> None:
        certification = propose_certification(team=self.team, user=self.user, saved_query_id=self.view.id)
        suggestion = self._suggest(kind)

        accepted = self._accept(suggestion.id)

        suggestion.refresh_from_db()
        reused_asset = {"certification_id": str(certification.id)}
        assert accepted["http_status"] == expected_http_status, accepted
        assert (suggestion.status, suggestion.created_asset, self._certification_status()) == (
            expected_suggestion_status,
            reused_asset if expected_suggestion_status == WarehouseSuggestionStatus.ACCEPTED else None,
            expected_certification_status,
        )

    def test_accepting_a_materialize_suggestion_materializes_the_view_on_the_chosen_interval(self) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.MATERIALIZE)

        accepted = self._accept(suggestion.id, {"refresh_interval_seconds": 12 * 60 * 60})

        self.view.refresh_from_db()
        assert accepted["http_status"] == status.HTTP_200_OK, accepted
        assert (self.view.is_materialized, accepted["created_asset"]["refresh_interval_seconds"]) == (
            True,
            12 * 60 * 60,
        )

    @parameterized.expand([("not_a_schedulable_interval", 7), ("past_the_largest_interval", 10**14)])
    def test_a_refused_interval_is_a_field_error_and_keeps_the_suggestion_open(
        self, _name: str, refresh_interval_seconds: int
    ) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.MATERIALIZE)

        refused = self._accept(suggestion.id, {"refresh_interval_seconds": refresh_interval_seconds})

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


class TestAcceptOutsideATransaction(NonAtomicAPIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(FLAG, return_value=True))
        self.enterContext(patch("products.data_modeling.backend.schedule.get_v2_saved_query_ids", return_value=set()))
        self.enterContext(patch.object(DataWarehouseSavedQuery, "_start_immediate_materialization"))
        self.view = create_view_in_dag(self.team, self.user)

    def test_a_failed_first_schedule_keeps_the_materialize_suggestion_open(self) -> None:
        suggestion = suggest(self.team.id, self.view.id, WarehouseSuggestionKind.MATERIALIZE)

        with patch(
            "products.data_modeling.backend.logic.schedule_reconcile.reconcile_dag_schedules",
            side_effect=RuntimeError("temporal is down"),
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/warehouse_suggestions/{suggestion.id}/accept/")

        suggestion.refresh_from_db()
        self.view.refresh_from_db()
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, response.json()
        assert (suggestion.status, self.view.is_materialized) == (WarehouseSuggestionStatus.PROPOSED, False)
