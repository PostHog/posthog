from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.cdp.backend.facade.models import HogFunction
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_MAX_LISTED = 20


class WebhookNotRegisteredCheck(HealthCheck):
    """Flag a source whose tables use webhook sync but that has no active webhook.

    These tables receive no webhook data. What the sync does instead depends on the source: a
    webhook-only table gets no data, Stripe skips a poll that would list the whole table, and other
    sources poll the vendor API, often reading the whole table on every run.
    """

    name = "webhook_not_registered"
    kind = "webhook_not_registered"
    owner = JobOwners.TEAM_WAREHOUSE_SOURCES
    policy = HealthExecutionPolicy(batch_size=50, max_concurrent=3)
    schedule = "50 7 * * *"
    active_since_days = 30
    access_controlled_resource = "external_data_source"
    remediation = Remediation(
        human="""
            Some tables on this source use webhook sync, but the source has no active webhook, so
            these tables get no webhook updates. Depending on the table, the sync either skips it or
            reads it from the source API instead, which can be slow and can read the whole table on
            every sync. Open the source (Data pipeline / Data warehouse → Sources), go to the Webhook
            tab, and create the webhook. If you can't create a webhook for this account, change the
            affected tables to incremental or full refresh sync instead.
        """,
        agent="""
            Confirm with `external-data-sources-retrieve` that the listed schemas use webhook sync.
            Have the user create the webhook from the source's Webhook tab, or enable it if it is
            off. If the account can't have a webhook, change the affected schemas to another sync
            type with `external-data-schemas-partial-update`. The check clears once the source has
            an enabled webhook or no webhook-synced schemas.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        name = issue.payload.get("pipeline_name") or issue.payload.get("source_type", "a webhook source")
        return AlertContent(
            title="Webhook isn't set up for webhook-synced tables",
            summary=f"{name} has tables set to webhook sync, but the source has no active webhook",
            link="/health/pipeline-status",
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        schemas = ExternalDataSchema.objects.filter(
            team_id__in=team_ids,
            deleted=False,
            should_sync=True,
            initial_sync_complete=True,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
        ).values_list("source_id", "name")

        schema_names_by_source: dict[str, list[str]] = {}
        for source_id, schema_name in schemas:
            schema_names_by_source.setdefault(str(source_id), []).append(schema_name)
        if not schema_names_by_source:
            return {}

        sources_with_webhook = {
            str(source_id)
            for source_id in HogFunction.objects.filter(
                team_id__in=team_ids,
                type="warehouse_source_webhook",
                enabled=True,
                deleted=False,
                inputs__source_id__value__in=list(schema_names_by_source),
            ).values_list("inputs__source_id__value", flat=True)
        }

        sources = (
            ExternalDataSource.objects.filter(
                pk__in=[pk for pk in schema_names_by_source if pk not in sources_with_webhook],
            )
            .exclude(deleted=True)
            .values_list("pk", "team_id", "prefix", "source_type")
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for source_pk, team_id, prefix, source_type in sources:
            issues.setdefault(team_id, []).append(
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "pipeline_type": "external_data_webhook",
                        "pipeline_id": str(source_pk),
                        "pipeline_name": prefix or source_type,
                        "source_type": source_type,
                        "affected_schemas": sorted(schema_names_by_source[str(source_pk)])[:_MAX_LISTED],
                    },
                    hash_keys=["pipeline_type", "pipeline_id"],
                )
            )

        return issues
