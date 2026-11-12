import dataclasses
from pathlib import Path
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

import yaml
from parameterized import parameterized

from posthog.constants import AvailableFeature

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_suggestions.backend.facade import api
from products.warehouse_suggestions.backend.facade.contracts import (
    CertifyPayload,
    DeprecatePayload,
    SourceRef,
    UnmaterializePayload,
)
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionMainSaving,
    WarehouseSuggestionStatus,
)
from products.warehouse_suggestions.backend.logic.query_notes import (
    ACCEPT_TOOL,
    DISMISS_TOOL,
    MCP_SHARE_STEP,
    materialize_summary,
    unmaterialize_summary,
)
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

from .factories import make_surfaced_suggestion, materialize_payload

QUERY_NOTES = "products.warehouse_suggestions.backend.logic.query_notes"
TOOLS_YAML = Path(__file__).parents[2] / "mcp" / "tools.yaml"
UNMATERIALIZE_PAYLOAD = UnmaterializePayload(
    subject_name="orders",
    refresh_seconds_per_month=7200.0,
    refresh_bytes_per_month=0.0,
    live_seconds_per_month=600.0,
    live_bytes_per_month=0.0,
    read_seconds=12.0,
    query_fingerprint="fingerprint",
)


class TestMaterializeSummary(SimpleTestCase):
    @parameterized.expand(
        [
            ("waiting", {}, "would save people about 40 minutes of waiting a month (estimated)"),
            (
                "background",
                {"main_saving": WarehouseSuggestionMainSaving.BACKGROUND, "background_seconds_saved_per_month": 7200.0},
                "would save about 2 hours of background work a month (estimated)",
            ),
            (
                "scanned",
                {"main_saving": WarehouseSuggestionMainSaving.SCANNED, "saves_bytes_per_month": 3.2 * 10**12},
                "would save about 3.2 TB of scanning a month (estimated)",
            ),
            ("older payload", {"main_saving": None}, "would save about 40 minutes of query time a month (estimated)"),
            ("known freshness", {"freshness_today_seconds": 3600}, "so its data would be up to 2 hours old"),
            (
                "unknown sources",
                {"unknown_sources": (SourceRef(name="stripe_charges", warehouse_table_id=None),)},
                "which adds up to 1 hour to the age of its source data",
            ),
            ("read time", {}, "Reading it takes about 20 seconds today"),
        ]
    )
    def test_states_the_saving_and_the_trade_off(self, _name: str, overrides: dict, expected: str) -> None:
        summary = materialize_summary(materialize_payload(**overrides), "orders")

        assert expected in summary
        assert "stripe_charges" not in summary

    @parameterized.expand(
        [
            ("refresh time", {}, "would save about 2 hours of background work a month"),
            (
                "scanned bytes when the time saving is small",
                {"refresh_seconds_per_month": 630.0, "refresh_bytes_per_month": 5 * 10**12},
                "would save about 5.0 TB of scanning a month",
            ),
        ]
    )
    def test_unmaterialize_leads_with_the_saving_that_qualified(
        self, _name: str, overrides: dict, expected: str
    ) -> None:
        payload = dataclasses.replace(UNMATERIALIZE_PAYLOAD, **overrides)

        assert expected in unmaterialize_summary(payload, "orders")

    def test_omits_read_time_when_unknown(self) -> None:
        assert "Reading it" not in materialize_summary(materialize_payload(read_seconds=None), "orders")

    def test_tool_names_exist_in_the_mcp_tools(self) -> None:
        tools = yaml.safe_load(TOOLS_YAML.read_text())["tools"]

        assert DISMISS_TOOL in tools
        assert "confirmed_action" in tools[ACCEPT_TOOL]


class TestSuggestionsForReadViews(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(f"{QUERY_NOTES}.is_warehouse_suggestions_enabled", return_value=True))
        self.orders = self._view("orders")
        self.sessions = self._view("sessions")

    def _view(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )

    def _restrict(self, view: DataWarehouseSavedQuery, access_level: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(view.id),
            organization_member=self.organization_membership,
            access_level=access_level,
        )

    def _notes(self, *view_ids: UUID, is_mcp_run: bool = True, can_write: bool = True) -> list | None:
        return api.suggestions_for_read_views(
            self.team, self.user, [str(view_id) for view_id in view_ids], is_mcp_run=is_mcp_run, can_write=can_write
        )

    def test_returns_open_surfaced_suggestions_on_views_the_user_can_read(self) -> None:
        read_only = self._view("read_only")
        hidden = self._view("hidden")
        dismissed = self._view("dismissed")
        unread = self._view("unread")
        make_surfaced_suggestion(self.team.id, self.orders.id)
        make_surfaced_suggestion(
            self.team.id, self.orders.id, kind=WarehouseSuggestionKind.UNMATERIALIZE, payload=UNMATERIALIZE_PAYLOAD
        )
        make_surfaced_suggestion(
            self.team.id,
            self.orders.id,
            kind=WarehouseSuggestionKind.CERTIFY,
            payload=CertifyPayload(subject_name="orders"),
        )
        make_surfaced_suggestion(
            self.team.id,
            self.sessions.id,
            kind=WarehouseSuggestionKind.DEPRECATE,
            payload=DeprecatePayload(
                subject_name="sessions", refresh_seconds_per_month=0.0, refresh_bytes_per_month=0.0
            ),
        )
        make_surfaced_suggestion(self.team.id, self.sessions.id, surfaced=False)
        make_surfaced_suggestion(self.team.id, read_only.id)
        make_surfaced_suggestion(self.team.id, hidden.id)
        WarehouseSuggestion.objects.for_team(self.team.id).filter(
            id=make_surfaced_suggestion(self.team.id, dismissed.id).id
        ).update(status=WarehouseSuggestionStatus.DISMISSED)
        make_surfaced_suggestion(self.team.id, unread.id)
        self._restrict(read_only, "viewer")
        self._restrict(hidden, "none")

        notes = self._notes(self.orders.id, self.sessions.id, read_only.id, hidden.id, dismissed.id)

        assert notes is not None
        assert sorted((note.view_name, note.kind, note.can_act) for note in notes) == [
            ("orders", WarehouseSuggestionKind.MATERIALIZE, True),
            ("orders", WarehouseSuggestionKind.UNMATERIALIZE, True),
            ("read_only", WarehouseSuggestionKind.MATERIALIZE, False),
        ]

    @parameterized.expand(
        [
            ("agent that can edit", True, None, True, "warehouse-suggestions-accept-prepare (id {id})"),
            ("caller without tools", False, None, True, "Review it at http"),
            ("mcp viewer", True, "viewer", True, MCP_SHARE_STEP),
            ("mcp read-only token", True, None, False, MCP_SHARE_STEP),
            ("posthog ai viewer", False, "viewer", True, "Accepting it needs edit access to the view, so share http"),
        ]
    )
    def test_next_step_follows_the_caller(
        self, _name: str, is_mcp_run: bool, access_level: str | None, can_write: bool, expected: str
    ) -> None:
        suggestion = make_surfaced_suggestion(self.team.id, self.orders.id)
        if access_level:
            self._restrict(self.orders, access_level)

        notes = self._notes(self.orders.id, is_mcp_run=is_mcp_run, can_write=can_write)

        assert notes is not None
        assert expected.format(id=suggestion.id) in notes[0].message
        assert notes[0].can_act is (access_level is None and can_write)

    @parameterized.expand(
        [
            ("no views read", False, (), []),
            ("flag off", True, ("orders",), None),
            ("no open suggestion", False, ("sessions",), []),
        ]
    )
    def test_early_exits(self, _name: str, flag_off: bool, views: tuple[str, ...], expected: list | None) -> None:
        make_surfaced_suggestion(self.team.id, self.orders.id)
        view_ids = [{"orders": self.orders, "sessions": self.sessions}[name].id for name in views]
        with patch(f"{QUERY_NOTES}.is_warehouse_suggestions_enabled", return_value=not flag_off):
            assert self._notes(*view_ids) == expected

    def test_skips_a_suggestion_whose_payload_cannot_be_read(self) -> None:
        unreadable = make_surfaced_suggestion(self.team.id, self.orders.id)
        WarehouseSuggestion.objects.for_team(self.team.id).filter(id=unreadable.id).update(payload_version=99)
        make_surfaced_suggestion(self.team.id, self.sessions.id)

        notes = self._notes(self.orders.id, self.sessions.id)

        assert notes is not None
        assert [note.view_name for note in notes] == ["sessions"]
