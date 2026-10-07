from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.db.models import F

from posthog.helpers.full_text_search import build_rank
from posthog.ingress.contracts import WebhookDelivery

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.contracts import (
    EmailDomainDnsRecord,
    EmailDomainVerification,
    FlowUtmUpdate,
    RecentWorkflow,
    TeamUtmDefaults,
    TierDecision,
    TwilioAccount,
    TwilioPhoneNumber,
    WorkflowActivitySummary,
    WorkflowSummary,
    WorkflowTaskDailyLimits,
)
from products.workflows.backend.models import HogFlow, TeamWorkflowsConfig
from products.workflows.backend.services import email_utm_defaults
from products.workflows.backend.services.batch_jobs import create_batch_job
from products.workflows.backend.services.email_sending_controls import (
    ensure_workflows_config,
    get_email_sending_state,
    set_email_sending_tier,
    suspend_email_sending,
    unsuspend_email_sending,
)
from products.workflows.backend.services.integration_usage import get_active_hog_flows_using_integration
from products.workflows.backend.services.template_input_usage import (
    filter_hog_flow_references_by_access_level,
    get_hog_flows_referencing_template_input_keys,
)
from products.workflows.backend.utils.email_sending_tiers import (
    MIN_EMAIL_SENDING_TIER,
    get_email_sending_tier_limits,
    max_email_sending_tier,
)
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences, validate_rrule

__all__ = [
    "MIN_EMAIL_SENDING_TIER",
    "compute_next_occurrences",
    "create_batch_job",
    "ensure_workflows_config",
    "filter_hog_flow_references_by_access_level",
    "get_email_sending_state",
    "get_email_sending_tier_limits",
    "get_hog_flows_referencing_template_input_keys",
    "max_email_sending_tier",
    "set_email_sending_tier",
    "suspend_email_sending",
    "unsuspend_email_sending",
    "validate_rrule",
]


class WorkflowNotFound(Exception):
    pass


class WorkflowAccessDenied(Exception):
    pass


class WorkflowArchived(Exception):
    pass


def search_workflows(
    *,
    project_id: int,
    query: str | None,
    access_control: UserAccessControl,
    limit: int,
    offset: int = 0,
    include_archived: bool = False,
    with_access_levels: bool = False,
    include_count: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Ranked full-text search over a project's workflows, in the result shape of core search.

    ``with_access_levels`` adds ``user_access_level``, the user's resolved level for each workflow.
    ``include_count=False`` skips the count query and reports a total of 0.
    """
    statuses = [HogFlow.State.DRAFT, HogFlow.State.ACTIVE]
    if include_archived:
        statuses.append(HogFlow.State.ARCHIVED)
    queryset = access_control.filter_queryset_by_access_level(
        HogFlow.objects.filter(team__project_id=project_id, status__in=statuses)
    )

    if query:
        queryset = queryset.annotate(rank=build_rank({"name": "A", "description": "C"}, query, config="simple"))
        queryset = queryset.filter(rank__gt=0.05).order_by("-rank")
    else:
        queryset = queryset.order_by(F("name").asc(nulls_first=True))

    total_count = queryset.count() if include_count else 0
    fields = ["id", "name", "description", "status", "created_by_id"]
    if query:
        fields.append("rank")

    rows = list(queryset[offset : offset + limit].values(*fields))
    access_levels = (
        access_control.bulk_object_access_levels("hog_flow", [(str(row["id"]), row["created_by_id"]) for row in rows])
        if with_access_levels
        else {}
    )

    results: list[dict[str, Any]] = []
    for workflow in rows:
        result: dict[str, Any] = {
            "type": "hog_flow",
            "result_id": str(workflow["id"]),
            "extra_fields": {
                "name": workflow["name"],
                "description": workflow["description"],
                "status": workflow["status"],
            },
        }
        if query:
            result["rank"] = workflow["rank"]
        if with_access_levels:
            result["user_access_level"] = access_levels.get(str(workflow["id"]))
        results.append(result)

    return results, total_count


def get_workflow_owner_id(*, team_id: int, workflow_id: UUID) -> int | None:
    try:
        return HogFlow.objects.values_list("created_by_id", flat=True).get(team_id=team_id, id=workflow_id)
    except HogFlow.DoesNotExist:
        raise WorkflowNotFound() from None


def workflow_exists(*, team_id: int, workflow_id: UUID) -> bool:
    return HogFlow.objects.filter(team_id=team_id, id=workflow_id).exists()


def get_workflow_task_daily_limits(*, team_id: int) -> WorkflowTaskDailyLimits:
    config = (
        TeamWorkflowsConfig.objects.filter(team_id=team_id)
        .only("workflow_task_rate_limit_per_day", "workflow_task_team_rate_limit_per_day")
        .first()
    )
    if config is None:
        return WorkflowTaskDailyLimits(per_workflow=None, per_team=None)
    return WorkflowTaskDailyLimits(
        per_workflow=config.workflow_task_rate_limit_per_day,
        per_team=config.workflow_task_team_rate_limit_per_day,
    )


def accept_github_event(delivery: WebhookDelivery) -> None:
    """The inbound GitHub App webhook enters workflows here, so its consumer needs no internal import."""
    # Deferred to keep the Kafka producer off the facade import path.
    from products.workflows.backend.github_workflow_events import emit_github_event  # noqa: PLC0415

    emit_github_event(delivery.event_type, dict(delivery.payload), delivery.delivery_id or "")


def accept_ses_event(delivery: WebhookDelivery) -> None:
    """The inbound SES events SNS topic enters workflows here, so its consumer needs no internal import."""
    # Deferred to keep the Celery task and the SNS callback client off the facade import path.
    from products.workflows.backend.services.ses_tenant_events import handle_ses_tenant_event  # noqa: PLC0415

    handle_ses_tenant_event(delivery)


def set_workflow_enabled(*, team_id: int, user_id: int, workflow_id: UUID, enabled: bool) -> str:
    """Flip a workflow between ``active`` and ``draft`` as ``user_id`` and return the new status.

    The same transition the lifecycle API tools make (enable is ``active``, disable is
    ``draft``); the scheduler fires only active workflows, so a disabled one stops at its
    next occurrence and keeps its schedule for when it is enabled again. Archived workflows
    are left alone. The user must hold editor access to the workflow, as in the API.
    """
    from posthog.models.user import User  # noqa: PLC0415 — keeps the user model off the facade import path

    from products.workflows.backend.presentation.views.hog_flow import (  # noqa: PLC0415 - heavy DRF import
        HogFlowSerializer,
    )

    hog_flow = HogFlow.objects.select_related("team").filter(team_id=team_id, id=workflow_id).first()
    if hog_flow is None:
        raise WorkflowNotFound()
    if hog_flow.status == HogFlow.State.ARCHIVED:
        raise WorkflowArchived()
    user = User.objects.get(id=user_id)
    if not UserAccessControl(user=user, team=hog_flow.team).check_access_level_for_object(hog_flow, "editor"):
        raise WorkflowAccessDenied()
    target = HogFlow.State.ACTIVE if enabled else HogFlow.State.DRAFT
    if hog_flow.status != target:
        if enabled:
            serializer = HogFlowSerializer(
                hog_flow,
                data={"status": target},
                partial=True,
                context={"team_id": team_id, "get_team": lambda: hog_flow.team},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        else:
            hog_flow.status = target
            hog_flow.save(update_fields=["status", "updated_at"])
    return str(hog_flow.status)


def get_workflow_names(*, team_id: int, workflow_ids: Iterable[str]) -> dict[str, str]:
    """Names keyed by the workflow id as a string. Deleted workflows are left out."""
    return {
        str(pk): (name or "")
        for pk, name in HogFlow.objects.filter(team_id=team_id, id__in=list(workflow_ids)).values_list("id", "name")
    }


def get_workflow_summary(*, team_id: int, workflow_id: str) -> WorkflowSummary:
    row = HogFlow.objects.filter(team_id=team_id, id=workflow_id).values("id", "name", "status").first()
    if row is None:
        raise WorkflowNotFound()
    return WorkflowSummary(id=str(row["id"]), name=row["name"] or "", status=row["status"])


def has_active_workflows(*, team_id: int) -> bool:
    return HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.ACTIVE).exists()


def has_active_workflow_for_warehouse_table(*, team_id: int, trigger_source: str, table_name: str) -> bool:
    return HogFlow.objects.filter(
        team_id=team_id,
        status=HogFlow.State.ACTIVE,
        trigger__type=trigger_source,
        trigger__table_name=table_name,
    ).exists()


def get_workflow_activity_summary(*, team_id: int, recent_limit: int) -> WorkflowActivitySummary:
    """Total and non-archived workflow counts, plus the most recently updated workflows."""
    qs = HogFlow.objects.filter(team_id=team_id)
    recent = qs.order_by("-updated_at")[:recent_limit].values("id", "name", "status", "updated_at")
    return WorkflowActivitySummary(
        total_count=qs.count(),
        active_count=qs.exclude(status=HogFlow.State.ARCHIVED).count(),
        recent=tuple(
            RecentWorkflow(
                id=str(row["id"]), name=row["name"] or "", status=row["status"], updated_at=row["updated_at"]
            )
            for row in recent
        ),
    )


def get_active_workflows_using_integration(*, team_id: int, integration_id: int) -> list[WorkflowSummary]:
    return [
        WorkflowSummary(id=str(flow.id), name=flow.name or "", status=flow.status)
        for flow in get_active_hog_flows_using_integration(team_id=team_id, integration_id=integration_id)
    ]


def recompute_email_sending_tier(team_id: int) -> TierDecision | None:
    # Deferred to keep the ClickHouse metrics client off the facade import path.
    from products.workflows.backend.services.email_sending_tier import (  # noqa: PLC0415
        recompute_email_sending_tier_for_team,
    )

    return recompute_email_sending_tier_for_team(team_id)


# The provider helpers look the provider class up on the providers package at call time, which
# also keeps boto3 and the Twilio client off the facade import path.


def create_ses_email_domain(
    domain: str, *, mail_from_subdomain: str, team_id: int, org_team_ids: Iterable[int] | None = None
) -> None:
    from products.workflows.backend import providers  # noqa: PLC0415

    providers.SESProvider().create_email_domain(
        domain, mail_from_subdomain=mail_from_subdomain, team_id=team_id, org_team_ids=org_team_ids
    )


def update_ses_mail_from_subdomain(domain: str, *, mail_from_subdomain: str) -> None:
    from products.workflows.backend import providers  # noqa: PLC0415

    providers.SESProvider().update_mail_from_subdomain(domain, mail_from_subdomain=mail_from_subdomain)


def verify_ses_email_domain(domain: str, *, mail_from_subdomain: str, team_id: int) -> EmailDomainVerification:
    from products.workflows.backend import providers  # noqa: PLC0415

    return providers.SESProvider().verify_email_domain(domain, mail_from_subdomain=mail_from_subdomain, team_id=team_id)


def delete_ses_identity(identity: str) -> None:
    from products.workflows.backend import providers  # noqa: PLC0415

    providers.SESProvider().delete_identity(identity)


def get_maildev_mock_dns_records() -> list[EmailDomainDnsRecord]:
    from products.workflows.backend import providers  # noqa: PLC0415

    return providers.MAILDEV_MOCK_DNS_RECORDS


def get_twilio_phone_numbers(*, account_sid: str, auth_token: str) -> list[TwilioPhoneNumber]:
    from products.workflows.backend import providers  # noqa: PLC0415

    return providers.TwilioProvider(account_sid=account_sid, auth_token=auth_token).get_phone_numbers()


def get_twilio_account_info(*, account_sid: str, auth_token: str) -> TwilioAccount:
    from products.workflows.backend import providers  # noqa: PLC0415

    return providers.TwilioProvider(account_sid=account_sid, auth_token=auth_token).get_account_info()


def load_team_utm_defaults(team_id: int) -> TeamUtmDefaults:
    return email_utm_defaults.load_team_utm_defaults(team_id)


def flow_ids_with_active_schedule(team_id: int) -> set[UUID]:
    return email_utm_defaults.flow_ids_with_active_schedule(team_id)


def seed_new_email_steps_with_utm_defaults(
    actions: list[dict[str, Any]], existing_action_ids: Iterable[str], defaults: TeamUtmDefaults
) -> None:
    email_utm_defaults.seed_new_email_actions(actions, existing_action_ids, defaults)


def release_edited_email_utm_keys(
    actions: list[dict[str, Any]],
    stored_actions: list[Any],
    stored_draft: dict[str, Any] | None,
    defaults: TeamUtmDefaults,
) -> None:
    email_utm_defaults.release_edited_keys(actions, stored_actions, stored_draft, defaults)


def plan_flow_utm_update(
    actions: list[Any], draft: dict[str, Any] | None, defaults: TeamUtmDefaults, enable_where_off: bool
) -> FlowUtmUpdate | None:
    return email_utm_defaults.plan_flow_update(actions, draft, defaults, enable_where_off)
