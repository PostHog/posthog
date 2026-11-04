from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.enrollment import enrolled_sources
from products.engineering_analytics.backend.tests._github_fixtures import (
    create_depot_source,
    create_github_source,
    enroll_team,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestEnrolledSources(BaseTest):
    @parameterized.expand([("github", ExternalDataSourceType.GITHUB), ("depot", ExternalDataSourceType.DEPOT)])
    def test_lists_only_enrolled_teams(self, _name: str, source_type: ExternalDataSourceType) -> None:
        # Both job-log sweeps and the census fan-out start here. An unenrolled team's CI logs and
        # census events must never reach its project.
        unenrolled = Team.objects.create(organization=self.organization, name="unenrolled")
        create = create_github_source if source_type == ExternalDataSourceType.GITHUB else create_depot_source
        enrolled_source = create(self.team)
        create(unenrolled)
        enroll_team(self.team)

        assert [source.id for source in enrolled_sources(source_type)] == [enrolled_source.id]
