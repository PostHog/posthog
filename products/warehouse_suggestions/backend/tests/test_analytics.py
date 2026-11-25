from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind
from products.warehouse_suggestions.backend.logic.analytics import SuggestionOutcome, report_outcomes
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

from .test_api import REPORT


class TestEstimatedSavingsOnEvents(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "materialize_reports_what_it_saves",
                WarehouseSuggestionKind.MATERIALIZE,
                {"saves_seconds_per_month": 300.0, "saves_bytes_per_month": 9e9},
                (300.0, 9e9),
            ),
            (
                "unmaterialize_reports_refresh_cost_minus_live_cost",
                WarehouseSuggestionKind.UNMATERIALIZE,
                {
                    "refresh_seconds_per_month": 500.0,
                    "live_seconds_per_month": 120.0,
                    "refresh_bytes_per_month": 4e9,
                    "live_bytes_per_month": 5e9,
                },
                (380.0, 0.0),
            ),
            (
                "deprecate_reports_its_refresh_cost",
                WarehouseSuggestionKind.DEPRECATE,
                {"refresh_seconds_per_month": 60.0, "refresh_bytes_per_month": 2e9},
                (60.0, 2e9),
            ),
            ("certify_saves_nothing", WarehouseSuggestionKind.CERTIFY, {"subject_name": "orders"}, (None, None)),
        ]
    )
    def test_reports_the_savings_the_payload_estimates(
        self,
        _name: str,
        kind: WarehouseSuggestionKind,
        payload: dict[str, Any],
        expected: tuple[float | None, float | None],
    ) -> None:
        suggestion = WarehouseSuggestion(kind=kind, payload=payload, score=1.0)

        with patch(REPORT) as report:
            report_outcomes(SuggestionOutcome.DISMISSED, [suggestion], team=MagicMock())

        properties = report.call_args.args[1]
        assert (
            properties["estimated_seconds_saved_per_month"],
            properties["estimated_bytes_saved_per_month"],
        ) == expected


class TestDeprecateChoiceOnEvents(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "marked_deprecated",
                WarehouseSuggestionKind.DEPRECATE,
                {"certification_id": "c", "stopped_materialization": True},
                "mark_deprecated",
            ),
            (
                "only_stopped_refreshes",
                WarehouseSuggestionKind.DEPRECATE,
                {"saved_query_id": "v"},
                "only_stop_refreshes",
            ),
            (
                "deleted",
                WarehouseSuggestionKind.DEPRECATE,
                {"saved_query_id": "v", "stopped_materialization": False},
                "delete",
            ),
            ("not_accepted_yet", WarehouseSuggestionKind.DEPRECATE, None, None),
            ("certified", WarehouseSuggestionKind.CERTIFY, {"certification_id": "c"}, None),
        ]
    )
    def test_reports_what_accepting_a_deprecate_suggestion_did(
        self,
        _name: str,
        kind: WarehouseSuggestionKind,
        created_asset: dict[str, Any] | None,
        expected: str | None,
    ) -> None:
        suggestion = WarehouseSuggestion(kind=kind, payload={}, score=1.0, created_asset=created_asset)

        with patch(REPORT) as report:
            report_outcomes(SuggestionOutcome.REPROPOSED, [suggestion], team=MagicMock())

        assert report.call_args.args[1]["deprecate_choice"] == expected
