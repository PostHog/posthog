from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.testing import create_access_control
from products.cdp.backend.models.hog_functions import HogFunction
from products.data_catalog.backend.facade.api import certifications_for_team, propose_certification
from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.api import get_declared_target, set_declared_target
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Edge, Node, NodeType
from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_suggestions.backend.facade.contracts import (
    CertifyPayload,
    DeprecatePayload,
    MaterializePayload,
    SuggestionAlreadyDecidedError,
    SuggestionPayload,
    UnmaterializePayload,
)
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionRefreshMode,
    WarehouseSuggestionStatus,
)
from products.warehouse_suggestions.backend.logic.accept import CertificationAcceptor
from products.warehouse_suggestions.backend.logic.candidates.unmaterialize import definition_fingerprint
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
ORDERS_SQL = "SELECT timestamp, event FROM events"
UPSTREAM_SQL = "SELECT * FROM postgres_orders"
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
UNMATERIALIZE_PAYLOAD = UnmaterializePayload(
    subject_name="orders",
    refresh_seconds_per_month=3600,
    refresh_bytes_per_month=10**9,
    live_seconds_per_month=20,
    live_bytes_per_month=10**6,
    read_seconds=5,
    query_fingerprint=definition_fingerprint([ORDERS_SQL]),
)
PAYLOADS: dict[WarehouseSuggestionKind, SuggestionPayload] = {
    WarehouseSuggestionKind.CERTIFY: CertifyPayload(subject_name="orders"),
    WarehouseSuggestionKind.DEPRECATE: DeprecatePayload(
        subject_name="orders", refresh_seconds_per_month=0, refresh_bytes_per_month=0
    ),
    WarehouseSuggestionKind.MATERIALIZE: MATERIALIZE_PAYLOAD,
    WarehouseSuggestionKind.UNMATERIALIZE: UNMATERIALIZE_PAYLOAD,
}


def create_view_in_dag(team: Team, user: User) -> DataWarehouseSavedQuery:
    view = DataWarehouseSavedQuery.objects.create(
        team=team,
        name="orders",
        query={"kind": "HogQLQuery", "query": ORDERS_SQL},
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


def materialize_in_place(view: DataWarehouseSavedQuery) -> DataWarehouseTable:
    table = DataWarehouseTable.objects.create(team=view.team, name=view.name, format="Delta")
    DataWarehouseSavedQuery.objects.filter(id=view.id).update(is_materialized=True, table=table)
    Node.objects.filter(saved_query=view).update(type=NodeType.MAT_VIEW)
    set_declared_target(Node.objects.get(saved_query=view), timedelta(hours=6))
    return table


def add_dependent_view(view: DataWarehouseSavedQuery) -> None:
    node = Node.objects.get(saved_query=view)
    dependent = DataWarehouseSavedQuery.objects.create(
        team=view.team, name="orders_daily", query={"kind": "HogQLQuery", "query": "SELECT * FROM orders"}
    )
    dependent_node = Node.objects.create(
        team=view.team, dag=node.dag, name="orders_daily", saved_query=dependent, type=NodeType.VIEW
    )
    Edge.objects.create(team=view.team, dag=node.dag, source=node, target=dependent_node)


def switch_to_incremental(view: DataWarehouseSavedQuery) -> None:
    DataWarehouseSavedQuery.objects.filter(id=view.id).update(incremental_config=STORED_DAY_KEY)


def add_an_upstream_view_over_postgres(view: DataWarehouseSavedQuery) -> list[str]:
    node = Node.objects.get(saved_query=view)
    source = ExternalDataSource.objects.create(
        team=view.team,
        source_id="postgres",
        connection_id="postgres",
        status="Completed",
        source_type=ExternalDataSourceType.POSTGRES,
    )
    postgres_table = DataWarehouseTable.objects.create(
        team=view.team, name="postgres_orders", format="Parquet", external_data_source=source
    )
    upstream_view = DataWarehouseSavedQuery.objects.create(
        team=view.team, name="orders_source", query={"kind": "HogQLQuery", "query": UPSTREAM_SQL}
    )
    upstream_node = Node.objects.create(
        team=view.team, dag=node.dag, name="orders_source", saved_query=upstream_view, type=NodeType.VIEW
    )
    table_node = Node.objects.create(
        team=view.team,
        dag=node.dag,
        name="postgres_orders",
        type=NodeType.TABLE,
        properties={"warehouse_table_id": str(postgres_table.id)},
    )
    Edge.objects.create(team=view.team, dag=node.dag, source=table_node, target=upstream_node)
    Edge.objects.create(team=view.team, dag=node.dag, source=upstream_node, target=node)
    return [ORDERS_SQL, UPSTREAM_SQL]


def make_the_postgres_source_direct(view: DataWarehouseSavedQuery) -> None:
    ExternalDataSource.objects.filter(team=view.team, source_id="postgres").update(
        access_method=ExternalDataSource.AccessMethod.DIRECT
    )


def change_the_upstream_query(view: DataWarehouseSavedQuery) -> None:
    DataWarehouseSavedQuery.objects.filter(team=view.team, name="orders_source").update(
        query={"kind": "HogQLQuery", "query": "SELECT * FROM postgres_orders WHERE 1 = 1"}
    )


def _restrict_table(view: DataWarehouseSavedQuery, table_name: str) -> None:
    view.team.organization.available_product_features = [
        {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
    ]
    view.team.organization.save()
    table = DataWarehouseTable.objects.get(team=view.team, name=table_name)
    create_access_control(
        team_id=view.team_id, resource="warehouse_table", resource_id=str(table.id), access_level="none"
    )


def restrict_the_postgres_table(view: DataWarehouseSavedQuery) -> None:
    _restrict_table(view, "postgres_orders")


def restrict_an_unrelated_table(view: DataWarehouseSavedQuery) -> None:
    DataWarehouseTable.objects.create(team=view.team, name="unrelated", format="Parquet")
    _restrict_table(view, "unrelated")


def read_a_system_table(view: DataWarehouseSavedQuery) -> None:
    node = Node.objects.get(saved_query=view)
    system_node = Node.objects.create(
        team=view.team,
        dag=node.dag,
        name="system.feature_flags",
        type=NodeType.TABLE,
        properties={"origin": "posthog"},
    )
    Edge.objects.create(team=view.team, dag=node.dag, source=system_node, target=node)


def change_query(view: DataWarehouseSavedQuery) -> None:
    DataWarehouseSavedQuery.objects.filter(id=view.id).update(
        query={"kind": "HogQLQuery", "query": "SELECT timestamp, event, properties FROM events"}
    )


def add_destination(view: DataWarehouseSavedQuery) -> None:
    HogFunction.objects.create(
        team=view.team,
        enabled=True,
        filters={"source": "data-warehouse-view", "data_warehouse": [{"table_name": view.name}]},
    )


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
        reused_asset = {"certification_id": str(certification.id), "stopped_materialization": False}
        assert accepted["http_status"] == expected_http_status, accepted
        assert (suggestion.status, suggestion.created_asset, self._certification_status()) == (
            expected_suggestion_status,
            reused_asset if expected_suggestion_status == WarehouseSuggestionStatus.ACCEPTED else None,
            expected_certification_status,
        )

    @parameterized.expand(
        [
            ("stops_a_materialized_view", True, {}, None, True),
            ("keeps_it_when_asked", True, {"keep_materialized": True}, None, False),
            ("leaves_a_plain_view_alone", False, {}, None, False),
            ("keeps_it_when_a_view_was_built_on_it", True, {}, add_dependent_view, False),
            ("keeps_it_when_it_feeds_a_destination", True, {}, add_destination, False),
        ]
    )
    def test_accepting_a_deprecate_suggestion_stops_refreshes_only_when_safe(
        self,
        _name: str,
        materialized: bool,
        body: dict,
        add_reader: Callable[[DataWarehouseSavedQuery], None] | None,
        expect_stopped: bool,
    ) -> None:
        table = materialize_in_place(self.view) if materialized else None
        view_join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=self.view.name,
            source_table_key="distinct_id",
            joining_table_name="events",
            joining_table_key="distinct_id",
            field_name="events",
        )
        draft = make_draft(fingerprint="deprecate:orders", subject_id=self.view.id)
        payload = DeprecatePayload(subject_name="orders", refresh_seconds_per_month=900, refresh_bytes_per_month=10**9)
        suggestion = ingest_surfaced(
            self.team.id, replace(draft, kind=WarehouseSuggestionKind.DEPRECATE, payload=payload)
        )
        if add_reader is not None:
            add_reader(self.view)

        with patch(REPORT) as report:
            accepted = self._accept(suggestion.id, body)

        self.view.refresh_from_db()
        assert accepted["http_status"] == status.HTTP_200_OK, accepted
        assert self._certification_status() == CertificationStatus.DEPRECATED
        assert accepted["created_asset"]["stopped_materialization"] is expect_stopped
        assert (Node.objects.get(team=self.team, saved_query=self.view).type == NodeType.VIEW) is (
            expect_stopped or not materialized
        )
        if table is not None:
            table.refresh_from_db()
            assert bool(table.deleted) is expect_stopped
        view_join.refresh_from_db()
        assert not view_join.deleted
        disabled_trigger = (
            ActivityLog.objects.filter(
                team_id=self.team.id, item_id=str(self.view.id), activity="materialization_disabled"
            )
            .values_list("detail__trigger", flat=True)
            .first()
        )
        assert disabled_trigger == (
            {"job_type": "warehouse_suggestion", "job_id": str(suggestion.id), "payload": {"kind": "deprecate"}}
            if expect_stopped
            else None
        )
        properties = report.call_args.args[1]
        assert (
            properties["stopped_materialization"],
            properties["refresh_seconds_per_month"],
            properties["refresh_bytes_per_month"],
        ) == ((True, 900, 10**9) if expect_stopped else (False, 0, 0))

    @parameterized.expand(
        [
            ("node_type_update", "products.data_modeling.backend.logic.saved_query_materialization.update_node_type"),
            (
                "frequency_target_clear",
                "products.data_modeling.backend.logic.schedule_reconcile.apply_saved_query_frequency_target",
            ),
        ]
    )
    def test_a_deprecate_whose_stop_fails_leaves_the_view_materialized_and_a_retry_stops_it(
        self, _name: str, failing_step: str
    ) -> None:
        table = materialize_in_place(self.view)
        suggestion = self._suggest(WarehouseSuggestionKind.DEPRECATE)

        with patch(failing_step, side_effect=RuntimeError("database is down")):
            failed = self._accept(suggestion.id)
        suggestion.refresh_from_db()
        self.view.refresh_from_db()
        table.refresh_from_db()
        untouched = (self.view.is_materialized, self.view.table_id, bool(table.deleted))
        retried = self._accept(suggestion.id)

        node = Node.objects.get(team=self.team, saved_query=self.view)
        assert failed["http_status"] == status.HTTP_500_INTERNAL_SERVER_ERROR, failed
        assert suggestion.status == WarehouseSuggestionStatus.PROPOSED
        assert untouched == (True, table.id, False)
        assert retried["created_asset"]["stopped_materialization"] is True, retried
        assert (node.type, get_declared_target(node)) == (NodeType.VIEW, None)

    @parameterized.expand(
        [
            ("stops_refreshes", None, None, status.HTTP_200_OK),
            ("stops_refreshes_with_an_upstream_view", add_an_upstream_view_over_postgres, None, status.HTTP_200_OK),
            ("a_view_was_built_on_it_since", None, add_dependent_view, status.HTTP_409_CONFLICT),
            ("it_refreshes_incrementally_since", None, switch_to_incremental, status.HTTP_409_CONFLICT),
            ("its_query_changed_since", None, change_query, status.HTTP_409_CONFLICT),
            (
                "an_upstream_query_changed_since",
                add_an_upstream_view_over_postgres,
                change_the_upstream_query,
                status.HTTP_409_CONFLICT,
            ),
            (
                "an_upstream_view_reads_a_direct_source_since",
                add_an_upstream_view_over_postgres,
                make_the_postgres_source_direct,
                status.HTTP_409_CONFLICT,
            ),
            (
                "an_upstream_table_was_restricted_since",
                add_an_upstream_view_over_postgres,
                restrict_the_postgres_table,
                status.HTTP_409_CONFLICT,
            ),
            (
                "stops_refreshes_when_only_an_unrelated_table_is_restricted",
                add_an_upstream_view_over_postgres,
                restrict_an_unrelated_table,
                status.HTTP_200_OK,
            ),
            ("it_reads_a_system_table_since", None, read_a_system_table, status.HTTP_409_CONFLICT),
        ]
    )
    def test_accepting_an_unmaterialize_suggestion_turns_the_view_back_into_a_plain_view(
        self,
        _name: str,
        build_before: Callable[[DataWarehouseSavedQuery], list[str]] | None,
        change_since: Callable[[DataWarehouseSavedQuery], None] | None,
        expected_status: int,
    ) -> None:
        table = materialize_in_place(self.view)
        queries = build_before(self.view) if build_before is not None else [ORDERS_SQL]
        payload = replace(UNMATERIALIZE_PAYLOAD, query_fingerprint=definition_fingerprint(queries))
        draft = make_draft(fingerprint="unmaterialize:orders", subject_id=self.view.id)
        suggestion = ingest_surfaced(
            self.team.id, replace(draft, kind=WarehouseSuggestionKind.UNMATERIALIZE, payload=payload)
        )
        if change_since is not None:
            change_since(self.view)

        with patch(REPORT) as report:
            accepted = self._accept(suggestion.id)

        table.refresh_from_db()
        suggestion.refresh_from_db()
        stopped = expected_status == status.HTTP_200_OK
        assert accepted["http_status"] == expected_status, accepted
        assert (
            Node.objects.get(team=self.team, saved_query=self.view).type,
            bool(table.deleted),
            suggestion.status,
        ) == (
            (NodeType.VIEW, True, WarehouseSuggestionStatus.ACCEPTED)
            if stopped
            else (NodeType.MAT_VIEW, False, WarehouseSuggestionStatus.PROPOSED)
        )
        if stopped:
            assert accepted["created_asset"] == {"saved_query_id": str(self.view.id)}
            assert report.call_args.args[1]["refresh_seconds_per_month"] == 3600

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
                "keep_materialized_on_a_materialize_suggestion",
                MATERIALIZE_PAYLOAD,
                {"keep_materialized": True},
                status.HTTP_400_BAD_REQUEST,
                "keep_materialized",
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
