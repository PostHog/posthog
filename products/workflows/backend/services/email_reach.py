from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import OrganizationMembership, Team


class EmailReachService:
    @staticmethod
    def counts(team: Team) -> dict[str, int]:
        verified_member_count = OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user__is_active=True, user__is_email_verified=True
        ).count()
        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        response = execute_hogql_query(
            query="SELECT count() FROM persons WHERE properties.email IS NOT NULL AND trim(toString(properties.email)) != ''",
            team=team,
            query_type="workflow_email_reach",
            settings=HogQLGlobalSettings(max_execution_time=10, timeout_overflow_mode="throw"),
        )
        return {
            "verified_member_count": verified_member_count,
            "project_email_count": int(response.results[0][0]),
        }
