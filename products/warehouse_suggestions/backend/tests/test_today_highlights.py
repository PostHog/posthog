from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature

from products.access_control.backend.models.access_control import AccessControl
from products.data_catalog.backend.facade.api import PendingGroup, PendingKind, TeamPendingReview
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.today.backend.facade.contracts import HighlightContext
from products.today.backend.facade.enums import HighlightLabel
from products.today.backend.facade.testing import highlight_context
from products.warehouse_suggestions.backend import today_highlights
from products.warehouse_suggestions.backend.facade.contracts import SuggestionDraft
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus
from products.warehouse_suggestions.backend.facade.today_highlights import HIGHLIGHT_SOURCES
from products.warehouse_suggestions.backend.logic.suggestions import transition_to
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

from .test_api import ingest_surfaced
from .test_suggestions import ingest_one, make_draft

METRICS = PendingGroup(kind=PendingKind.METRICS, noun="metric", count=3, sample_names=[])
RELATIONSHIPS = PendingGroup(kind=PendingKind.RELATIONSHIPS, noun="relationship", count=2, sample_names=[])
ONE_CERTIFICATION = PendingGroup(kind=PendingKind.CERTIFICATIONS, noun="certification", count=1, sample_names=[])
FLAG = "products.warehouse_suggestions.backend.logic.access.is_warehouse_suggestions_enabled"


class TestCatalogApprovalsHighlight(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "one item uses the singular",
                [ONE_CERTIFICATION],
                0,
                "1 certification waits for approval",
                "Review it in the data catalog.",
                "/data-catalog?tab=certifications",
            ),
            (
                "several queues join their counts and link the first queue",
                [METRICS, RELATIONSHIPS, ONE_CERTIFICATION],
                0,
                "3 metrics, 2 relationships and 1 certification wait for approval",
                "Review them in the data catalog.",
                "/data-catalog?tab=metrics",
            ),
            (
                "certification suggestions join the proposals in one item",
                [RELATIONSHIPS],
                3,
                "2 relationships and 3 certification suggestions wait for approval",
                "Review them in the data catalog.",
                "/data-catalog?tab=relationships",
            ),
            (
                "certification suggestions alone still make an item",
                [],
                1,
                "1 certification suggestion waits for approval",
                "Review it in the data catalog.",
                "/data-catalog?tab=certifications",
            ),
        ]
    )
    def test_proposals_and_suggestions_are_one_opportunity_item(
        self, _name: str, groups: list[PendingGroup], suggested: int, title: str, detail: str, url: str
    ) -> None:
        review = (
            TeamPendingReview(team_id=1, team_name="Team", groups=groups, total=sum(group.count for group in groups))
            if groups
            else None
        )
        registered = next(source for source in HIGHLIGHT_SOURCES if source.name == "data_catalog_approvals")

        with self._catalog(review=review, suggested=suggested, can_approve=True):
            found = registered.find(self._context())

        assert len(found.items) == 1
        item = found.items[0]
        assert (item.title, item.detail, item.url) == (title, detail, url)
        assert item.label == HighlightLabel.OPPORTUNITY
        assert (item.importance, item.relevance) == (0.5, 1.0)
        assert registered.scopes == ("data_catalog:read", "data_catalog_approval:write")

    @parameterized.expand([("cannot approve", False, 2), ("nothing to review", True, 0)])
    def test_no_item(self, _name: str, can_approve: bool, suggested: int) -> None:
        with self._catalog(review=None, suggested=suggested, can_approve=can_approve):
            found = today_highlights.find_catalog_approvals(self._context())

        assert found.items == ()

    def _catalog(
        self, *, review: TeamPendingReview | None, suggested: int, can_approve: bool
    ) -> AbstractContextManager[object]:
        access = MagicMock()
        access.check_access_level_for_resource.side_effect = lambda resource, level: (
            can_approve and (resource, level) == ("data_catalog", "editor")
        )
        return patch.multiple(
            today_highlights,
            build_team_pending_review=MagicMock(return_value=review),
            actionable_open_count=MagicMock(return_value=suggested),
            UserAccessControl=MagicMock(return_value=access),
        )

    def _context(self) -> HighlightContext:
        return cast(
            HighlightContext,
            SimpleNamespace(
                team=SimpleNamespace(id=1),
                user=SimpleNamespace(id=1),
                guard=lambda _name, provider, _default: provider(),
                allows=lambda *_required: True,
            ),
        )


class TestModelSuggestionsHighlight(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = self.enterContext(patch(FLAG, return_value=True))

    def test_counts_the_open_model_suggestions_the_viewer_can_act_on(self) -> None:
        self._suggest(WarehouseSuggestionKind.MATERIALIZE, self._view("orders").id)
        self._suggest(WarehouseSuggestionKind.UNMATERIALIZE, self._view("events_daily").id)
        self._suggest(WarehouseSuggestionKind.CERTIFY, self._view("users").id)
        ingest_one(self.team.id, self._draft(WarehouseSuggestionKind.MATERIALIZE, self._view("unsurfaced").id))
        dismissed = self._suggest(WarehouseSuggestionKind.MATERIALIZE, self._view("dismissed").id)
        transition_to(dismissed.id, self.team.id, WarehouseSuggestionStatus.DISMISSED, user_id=self.user.id)
        read_only = self._view("read_only")
        self._suggest(WarehouseSuggestionKind.MATERIALIZE, read_only.id)
        self._restrict_view(read_only.id, "viewer")

        found = today_highlights.find_model_suggestions(self._context())

        assert [(item.title, item.detail, item.url) for item in found.items] == [
            ("2 model suggestions wait for review", "Review them in Models.", "/models?tab=models")
        ]

    @parameterized.expand(
        [
            ("session", None, 1),
            ("umbrella warehouse scope", frozenset({"warehouse_objects:write"}), 1),
            ("view scope", frozenset({"warehouse_view:write"}), 1),
            ("read only view scope", frozenset({"warehouse_view:read"}), 0),
            ("table scope", frozenset({"warehouse_table:write"}), 0),
            ("catalog scopes only", frozenset({"data_catalog:read", "data_catalog_approval:write"}), 0),
        ]
    )
    def test_counts_only_subjects_the_token_can_write(
        self, _name: str, scopes: frozenset[str] | None, expected_items: int
    ) -> None:
        self._suggest(WarehouseSuggestionKind.MATERIALIZE, self._view("orders").id)

        found = today_highlights.find_model_suggestions(self._context(scopes))

        assert len(found.items) == expected_items

    def test_no_item_when_suggestions_are_off(self) -> None:
        self._suggest(WarehouseSuggestionKind.MATERIALIZE, self._view("orders").id)
        self.flag.return_value = False

        assert today_highlights.find_model_suggestions(self._context()).items == ()

    def test_a_failed_suggestion_count_keeps_the_catalog_proposals(self) -> None:
        review = TeamPendingReview(team_id=self.team.id, team_name="Team", groups=[ONE_CERTIFICATION], total=1)
        self.flag.side_effect = RuntimeError("flag service down")

        with patch.object(today_highlights, "build_team_pending_review", return_value=review):
            found = today_highlights.find_catalog_approvals(self._context())

        assert [item.title for item in found.items] == ["1 certification waits for approval"]

    def _context(self, scopes: frozenset[str] | None = None) -> HighlightContext:
        return highlight_context(team=self.team, user=self.user, today=date(2026, 10, 27), scopes=scopes)

    def _view(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )

    def _draft(self, kind: WarehouseSuggestionKind, view_id: UUID) -> SuggestionDraft:
        return replace(make_draft(fingerprint=f"{kind}:{view_id}", subject_id=view_id), kind=kind)

    def _suggest(self, kind: WarehouseSuggestionKind, view_id: UUID) -> WarehouseSuggestion:
        return ingest_surfaced(self.team.id, self._draft(kind, view_id))

    def _restrict_view(self, view_id: UUID, access_level: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(view_id),
            organization_member=self.organization_membership,
            access_level=access_level,
        )
