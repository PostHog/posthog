from dataclasses import replace
from uuid import UUID

from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.data_catalog.backend.facade.api import certifications_for_team, propose_certification
from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Node, NodeType
from products.warehouse_suggestions.backend.facade.contracts import (
    CertifyPayload,
    DeprecatePayload,
    MaterializePayload,
    SuggestionAlreadyDecidedError,
    SuggestionPayload,
)
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionRefreshMode,
    WarehouseSuggestionStatus,
)
from products.warehouse_suggestions.backend.logic.accept import CertificationAcceptor
from products.warehouse_suggestions.backend.logic.suggestions import HUMAN_TRANSITIONS, transition_to
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

from .test_api import ingest_surfaced
from .test_suggestions import make_draft

FLAG = "products.warehouse_suggestions.backend.presentation.views.is_warehouse_suggestions_enabled"
DAY_SECONDS = 24 * 60 * 60
REPORT = "products.warehouse_suggestions.backend.logic.analytics.report_user_or_team_action"
DAY_KEYS = {"refresh_mode": "incremental", "incremental_key": "day", "unique_key": ["day"]}
DAILY_COUNTS = "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day"
DAILY_COUNT_COLUMNS = {
    "day": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime64(6, 'UTC')"},
    "c": {"hogql": "IntegerDatabaseField", "clickhouse": "UInt64"},
}
STORED_DAY_KEY = {"enabled": True, "incremental_key": "day", "unique_key": ["day"], "lookback_seconds": 0}
MATERIALIZE_PAYLOAD = MaterializePayload(
    subject_name="orders",
    refresh_interval_seconds=DAY_SECONDS,
    saves_seconds_per_month=900,
    saves_bytes_per_month=0,
    freshness_today_seconds=None,
    freshness_after_seconds=DAY_SECONDS,
    live_sources=(),
    unknown_sources=(),
)
INCREMENTAL_DAY_PAYLOAD = replace(
    MATERIALIZE_PAYLOAD,
    refresh_mode=WarehouseSuggestionRefreshMode.INCREMENTAL,
    incremental_key="day",
    unique_key=("day",),
)
PAYLOADS: dict[WarehouseSuggestionKind, SuggestionPayload] = {
    WarehouseSuggestionKind.CERTIFY: CertifyPayload(subject_name="orders"),
    WarehouseSuggestionKind.DEPRECATE: DeprecatePayload(
        subject_name="orders", refresh_seconds_per_month=0, refresh_bytes_per_month=0
    ),
    WarehouseSuggestionKind.MATERIALIZE: MATERIALIZE_PAYLOAD,
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

    def _suggest_materialize(self, payload: MaterializePayload) -> WarehouseSuggestion:
        draft = make_draft(fingerprint="materialize:orders", subject_id=self.view.id)
        return ingest_surfaced(self.team.id, replace(draft, kind=WarehouseSuggestionKind.MATERIALIZE, payload=payload))

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
        assert (
            Node.objects.get(team=self.team, saved_query=self.view).type,
            accepted["created_asset"]["refresh_interval_seconds"],
        ) == (
            NodeType.MAT_VIEW,
            12 * 60 * 60,
        )

    @parameterized.expand(
        [
            (
                "query_still_groups_by_the_key",
                DAILY_COUNTS,
                INCREMENTAL_DAY_PAYLOAD,
                status.HTTP_200_OK,
                STORED_DAY_KEY,
            ),
            (
                "query_changed_since_the_suggestion",
                "SELECT timestamp, event FROM events",
                INCREMENTAL_DAY_PAYLOAD,
                status.HTTP_409_CONFLICT,
                STORED_DAY_KEY,
            ),
            (
                "query_no_longer_groups",
                "SELECT toStartOfDay(timestamp) AS day FROM events",
                INCREMENTAL_DAY_PAYLOAD,
                status.HTTP_409_CONFLICT,
                STORED_DAY_KEY,
            ),
            ("full_refresh_clears_leftover_keys", DAILY_COUNTS, MATERIALIZE_PAYLOAD, status.HTTP_200_OK, None),
        ]
    )
    def test_accepting_applies_the_refresh_mode_the_suggestion_shows(
        self,
        _name: str,
        hogql: str,
        payload: MaterializePayload,
        expected_status: int,
        expected_config: dict | None,
    ) -> None:
        DataWarehouseSavedQuery.objects.filter(id=self.view.id).update(
            query={"kind": "HogQLQuery", "query": hogql}, columns=DAILY_COUNT_COLUMNS, incremental_config=STORED_DAY_KEY
        )
        suggestion = self._suggest_materialize(payload)

        accepted = self._accept(suggestion.id)

        self.view.refresh_from_db()
        assert (accepted["http_status"], self.view.incremental_config) == (expected_status, expected_config), accepted

    def _suggest_and_accept(self, payload: SuggestionPayload, body: dict) -> tuple[dict, list]:
        DataWarehouseSavedQuery.objects.filter(id=self.view.id).update(
            query={"kind": "HogQLQuery", "query": DAILY_COUNTS}
        )
        kind = (
            WarehouseSuggestionKind.MATERIALIZE
            if isinstance(payload, MaterializePayload)
            else WarehouseSuggestionKind.CERTIFY
        )
        draft = make_draft(fingerprint=f"{kind}:orders", subject_id=self.view.id)
        suggestion = ingest_surfaced(self.team.id, replace(draft, kind=kind, payload=payload))
        with patch(REPORT) as report:
            accepted = self._accept(suggestion.id, body)
        self.view.refresh_from_db()
        return accepted, [call.args[1]["changed_fields"] for call in report.call_args_list]

    @parameterized.expand(
        [
            (
                "chosen_keys_replace_a_full_refresh",
                MATERIALIZE_PAYLOAD,
                DAY_KEYS,
                STORED_DAY_KEY,
                ["refresh_mode", "incremental_key", "unique_key"],
            ),
            (
                "chosen_full_refresh_replaces_keys",
                INCREMENTAL_DAY_PAYLOAD,
                {"refresh_mode": "full"},
                None,
                ["refresh_mode"],
            ),
        ]
    )
    def test_a_person_can_change_the_refresh_before_accepting(
        self, _name: str, payload: MaterializePayload, body: dict, expected_config: dict | None, changed: list[str]
    ) -> None:
        accepted, reported_changes = self._suggest_and_accept(payload, body)

        assert accepted["http_status"] == status.HTTP_200_OK, accepted
        assert (self.view.incremental_config, reported_changes) == (expected_config, [changed])

    @parameterized.expand(
        [
            (
                "hostile_key",
                INCREMENTAL_DAY_PAYLOAD,
                {"incremental_key": 'day"; DROP TABLE events; --'},
                status.HTTP_400_BAD_REQUEST,
                "incremental_key",
            ),
            (
                "aggregate_in_a_chosen_unique_key",
                MATERIALIZE_PAYLOAD,
                {**DAY_KEYS, "unique_key": ["day", "c"]},
                status.HTTP_400_BAD_REQUEST,
                "unique_key",
            ),
            (
                "keys_with_a_full_refresh",
                MATERIALIZE_PAYLOAD,
                {"incremental_key": "day"},
                status.HTTP_400_BAD_REQUEST,
                "refresh_mode",
            ),
            (
                "an_option_for_another_kind",
                PAYLOADS[WarehouseSuggestionKind.CERTIFY],
                {"refresh_interval_seconds": 60 * 60},
                status.HTTP_400_BAD_REQUEST,
                "refresh_interval_seconds",
            ),
            (
                "lookback_only_on_stale_suggested_keys",
                replace(INCREMENTAL_DAY_PAYLOAD, incremental_key="hour", unique_key=("hour",)),
                {"lookback_seconds": 60 * 60},
                status.HTTP_409_CONFLICT,
                None,
            ),
        ]
    )
    def test_a_refused_change_writes_nothing(
        self,
        _name: str,
        payload: SuggestionPayload,
        body: dict,
        expected_status: int,
        expected_attr: str | None,
    ) -> None:
        accepted, reported_changes = self._suggest_and_accept(payload, body)

        assert (accepted["http_status"], accepted.get("attr")) == (expected_status, expected_attr), accepted
        assert (self.view.incremental_config, reported_changes) == (None, [])

    @parameterized.expand([("not_a_schedulable_interval", 7), ("past_the_largest_interval", 10**14)])
    def test_a_refused_interval_is_a_field_error_and_keeps_the_suggestion_open(
        self, _name: str, refresh_interval_seconds: int
    ) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.MATERIALIZE)

        refused = self._accept(suggestion.id, {"refresh_interval_seconds": refresh_interval_seconds})

        suggestion.refresh_from_db()
        assert (refused["http_status"], refused["attr"]) == (status.HTTP_400_BAD_REQUEST, "refresh_interval_seconds")
        assert suggestion.status == WarehouseSuggestionStatus.PROPOSED

    @parameterized.expand(
        [
            (
                "every_accept_scope",
                ["warehouse_objects:write", "data_catalog_approval:write", "warehouse_view:write"],
                status.HTTP_200_OK,
            ),
            (
                "per_kind_scopes_a_cli_key_carries",
                ["data_catalog_approval:write", "warehouse_view:write"],
                status.HTTP_200_OK,
            ),
            (
                "no_view_write_scope",
                ["warehouse_objects:write", "data_catalog_approval:write"],
                status.HTTP_403_FORBIDDEN,
            ),
        ]
    )
    def test_a_token_needs_view_write_to_accept_a_materialize_suggestion(
        self, _name: str, scopes: list[str], expected_status: int
    ) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.MATERIALIZE)
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="k", user=self.user, secure_value=hash_key_value(raw), scopes=scopes)
        self.client.logout()

        response = self.client.post(f"{self.url}/{suggestion.id}/accept/", HTTP_AUTHORIZATION=f"Bearer {raw}")

        assert response.status_code == expected_status, response.json()

    def test_a_dismiss_that_arrives_while_the_acceptor_runs_loses(self) -> None:
        suggestion = self._suggest(WarehouseSuggestionKind.CERTIFY)
        apply_certification = CertificationAcceptor.accept
        dismissals: list[Exception] = []

        def dismiss_then_apply(acceptor, row, payload, request):
            try:
                transition_to(
                    row.id,
                    self.team.id,
                    WarehouseSuggestionStatus.DISMISSED,
                    user_id=self.user.id,
                    transitions=HUMAN_TRANSITIONS,
                )
            except SuggestionAlreadyDecidedError as error:
                dismissals.append(error)
            return apply_certification(acceptor, row, payload, request)

        with patch.object(CertificationAcceptor, "accept", autospec=True, side_effect=dismiss_then_apply):
            accepted = self._accept(suggestion.id)

        suggestion.refresh_from_db()
        assert accepted["http_status"] == status.HTTP_200_OK, accepted
        assert (suggestion.status, len(dismissals), self._certification_status()) == (
            WarehouseSuggestionStatus.ACCEPTED,
            1,
            CertificationStatus.CERTIFIED,
        )

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
        assert (suggestion.status, Node.objects.get(team=self.team, saved_query=self.view).type) == (
            WarehouseSuggestionStatus.PROPOSED,
            NodeType.VIEW,
        )
