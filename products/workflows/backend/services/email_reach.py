from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Integration, OrganizationMembership, Team, User


@frozen
class EmailSenderEligibility:
    integration_id: int
    provider: str
    is_verified: bool


@frozen
class EmailReach:
    verified_member_count: int
    project_email_count: int
    email_senders: tuple[EmailSenderEligibility, ...]


class EmailReachService:
    @staticmethod
    def counts(team: Team, user: User) -> EmailReach:
        verified_member_count = OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user__is_active=True, user__is_email_verified=True
        ).count()
        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        response = execute_hogql_query(
            query="SELECT count() FROM persons WHERE properties.email IS NOT NULL AND trim(toString(properties.email)) != ''",
            team=team,
            user=user,
            query_type="workflow_email_reach",
            settings=HogQLGlobalSettings(max_execution_time=10, timeout_overflow_mode="throw"),
        )
        return EmailReach(
            verified_member_count=verified_member_count,
            project_email_count=int(response.results[0][0]),
            email_senders=tuple(
                EmailSenderEligibility(
                    integration_id=integration.id,
                    provider=str(integration.config.get("provider", "ses")),
                    is_verified=integration.config.get("verified") is True,
                )
                for integration in Integration.objects.filter(team_id=team.id, kind="email")
                .only("id", "config")
                .order_by("id")
            ),
        )
