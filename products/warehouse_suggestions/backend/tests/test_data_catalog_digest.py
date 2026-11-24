from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team

from products.access_control.backend.models.access_control import AccessControl
from products.data_catalog.backend.facade.contracts import DigestRow
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_suggestions.backend.facade.contracts import CertifyPayload
from products.warehouse_suggestions.backend.facade.data_catalog_digest import DIGEST_SOURCES
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

from .test_suggestions import ingest_one, make_draft

ACCESS_FLAG = "products.warehouse_suggestions.backend.logic.access.is_warehouse_suggestions_enabled"
DIGEST_FLAG = "products.warehouse_suggestions.backend.data_catalog_digest.is_warehouse_suggestions_enabled"


class TestDataCatalogDigestSource(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(ACCESS_FLAG, return_value=True))
        self.digest_flag = self.enterContext(patch(DIGEST_FLAG, return_value=True))
        (self.source,) = DIGEST_SOURCES

    def test_groups_suggestions_by_where_they_are_reviewed_and_counts_the_new_ones(self) -> None:
        self._suggest(self.team, WarehouseSuggestionKind.MATERIALIZE, "orders", surfaced_days_ago=2)
        self._suggest(self.team, WarehouseSuggestionKind.DEPRECATE, "old_rollup", surfaced_days_ago=10)
        self._suggest(self.team, WarehouseSuggestionKind.CERTIFY, "users", surfaced_days_ago=10)

        rows = self.source.rows(self.team, self.user, timezone.now() - timedelta(days=7))

        assert rows == [
            DigestRow(
                noun="certification suggestion",
                count=1,
                new_count=0,
                sample_names=["users"],
                path="/data-catalog?tab=suggestions",
            ),
            DigestRow(
                noun="model suggestion",
                count=2,
                new_count=1,
                sample_names=["old_rollup", "orders"],
                path="/models?tab=models",
            ),
        ]

    @parameterized.expand(
        [
            ("catalog editor", "editor", ["certification suggestion", "model suggestion"]),
            ("catalog viewer", "viewer", ["model suggestion"]),
        ]
    )
    def test_lists_catalog_suggestions_only_for_people_who_can_approve_them(
        self, _name: str, catalog_level: str, expected_nouns: list[str]
    ) -> None:
        self._suggest(self.team, WarehouseSuggestionKind.CERTIFY, "users", surfaced_days_ago=1)
        self._suggest(self.team, WarehouseSuggestionKind.MATERIALIZE, "orders", surfaced_days_ago=1)
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        AccessControl.objects.create(team=self.team, resource="data_catalog", access_level=catalog_level)

        rows = self.source.rows(self.team, self.user, timezone.now() - timedelta(days=7))

        assert [row.noun for row in rows] == expected_nouns

    @parameterized.expand([("flag on", True, True), ("flag off", False, False)])
    def test_reports_only_teams_with_a_suggestion_on_show(self, _name: str, enabled: bool, expected: bool) -> None:
        self.digest_flag.return_value = enabled
        quiet_team = Team.objects.create(organization=self.organization, name="Quiet")
        self._suggest(self.team, WarehouseSuggestionKind.MATERIALIZE, "orders", surfaced_days_ago=1)
        self._suggest(quiet_team, WarehouseSuggestionKind.MATERIALIZE, "orders", surfaced_days_ago=None)

        assert self.source.teams_with_rows([self.team, quiet_team]) == ({self.team.id} if expected else set())

    def _suggest(
        self, team: Team, kind: WarehouseSuggestionKind, name: str, surfaced_days_ago: int | None
    ) -> WarehouseSuggestion:
        view_id = self._view(team, name)
        draft = replace(
            make_draft(fingerprint=f"{kind}:{view_id}", subject_id=view_id),
            kind=kind,
            payload=CertifyPayload(subject_name=name),
        )
        suggestion = ingest_one(team.id, draft)
        if surfaced_days_ago is not None:
            WarehouseSuggestion.objects.for_team(team.id).filter(id=suggestion.id).update(
                surfaced_at=timezone.now() - timedelta(days=surfaced_days_ago)
            )
        return suggestion

    def _view(self, team: Team, name: str) -> UUID:
        return DataWarehouseSavedQuery.objects.create(
            team=team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        ).id
