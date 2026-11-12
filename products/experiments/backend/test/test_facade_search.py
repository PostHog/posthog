from posthog.test.base import APIBaseTest
from unittest.mock import Mock

from parameterized import parameterized

from posthog.api.search import ENTITY_MAP, EntityConfig, search_entities
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.experiments.backend.facade.search import search_experiments
from products.experiments.backend.facade.testing import create_experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestSearchExperiments(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._create("Revenue uplift", description="Checkout copy")
        self._create("Churn reduction", description="Revenue retention")
        self._create("Onboarding")
        self._create("Revenue revenue", deleted=True)
        hidden = self._create("Revenue hidden")
        AccessControl.objects.create(
            team=self.team, resource="experiment", resource_id=str(hidden), access_level="none"
        )
        self._create("Revenue elsewhere", team=Team.objects.create(organization=self.organization))
        self.access = UserAccessControl(user=self.user, team=self.team)

    def _create(
        self, name: str, *, description: str | None = None, deleted: bool = False, team: Team | None = None
    ) -> int:
        team = team or self.team
        flag = FeatureFlag.objects.create(team=team, key=f"flag-{name.lower().replace(' ', '-')}")
        return create_experiment(
            team_id=team.id, feature_flag_id=flag.id, name=name, description=description, deleted=deleted
        )

    # The facade must return what the core search union returns for the same entity config, so a search
    # can serve experiments from either one.
    @parameterized.expand(
        [
            ("listing", None, True, False, ["Churn reduction", "Onboarding", "Revenue revenue", "Revenue uplift"]),
            ("listing_live", None, False, True, ["Churn reduction", "Onboarding", "Revenue uplift"]),
            ("ranked", "revenue", True, True, ["Revenue revenue", "Revenue uplift", "Churn reduction"]),
            ("ranked_live", "revenue", False, False, ["Revenue uplift", "Churn reduction"]),
        ]
    )
    def test_results_match_the_core_search_union(
        self, _name: str, query: str | None, include_deleted: bool, with_access_levels: bool, expected: list[str]
    ) -> None:
        config: EntityConfig = {
            **ENTITY_MAP["experiment"],
            "filters": {} if include_deleted else {"deleted": False},
        }
        union_results, union_counts, _ = search_entities(
            {"experiment"},
            query,
            self.team.project_id,
            Mock(user_access_control=self.access),
            {"experiment": config},
            annotate_access_levels=self.access if with_access_levels else None,
            facade_searches={},
        )

        results, count = search_experiments(
            project_id=self.team.project_id,
            query=query,
            access_control=self.access,
            limit=25,
            include_deleted=include_deleted,
            with_access_levels=with_access_levels,
        )

        assert [result["extra_fields"]["name"] for result in results] == expected
        assert results == union_results
        assert union_counts is not None
        assert count == union_counts["experiment"]
