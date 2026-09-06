from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

import structlog

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.services.workflow_email_health import (
    PAUSED_BY_STAFF,
    pause_workflow_email_sending,
    resume_workflow_email_sending,
)

logger = structlog.get_logger(__name__)

# What the customer is told when staff pause a workflow by hand rather than the detector doing it.
# Deliberately vague about the trigger: staff reach for this for reasons the detector cannot see,
# such as a report from a mailbox provider.
STAFF_PAUSE_REASON = "PostHog staff paused this workflow's email to protect delivery for everyone."


class HogFlowScheduleInline(admin.TabularInline):
    model = HogFlowSchedule
    extra = 0
    readonly_fields = ("id", "rrule", "starts_at", "timezone", "variables", "status", "next_run_at")
    fields = ("rrule", "starts_at", "timezone", "variables", "status", "next_run_at")
    ordering = ("-created_at",)
    max_num = 10
    show_change_link = False


@admin.register(HogFlow)
class HogFlowAdmin(admin.ModelAdmin):
    inlines = [HogFlowScheduleInline]
    list_display = ("id", "name", "status", "version", "team_link", "email_sending_state", "created_at")
    list_filter = (
        ("status", admin.ChoicesFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
        ("email_sending_paused_at", admin.EmptyFieldListFilter),
    )
    list_select_related = ("team",)
    search_fields = ("name", "team__name", "team__organization__name")
    ordering = ("-created_at",)
    actions = ("pause_email_sending", "resume_email_sending")
    readonly_fields = (
        "id",
        "version",
        "team",
        "team_link",
        "created_by",
        "created_at",
        "updated_at",
        "trigger",
        "trigger_masking",
        "conversion",
        "edges",
        "actions",
        "variables",
        "billable_action_types",
        "email_sending_paused_at",
        "email_sending_paused_reason",
        "email_sending_resumed_at",
    )
    fields = (
        "name",
        "description",
        "status",
        "exit_condition",
        "abort_action",
        "version",
        "team_link",
        "created_by",
        "created_at",
        "updated_at",
        "trigger",
        "trigger_masking",
        "conversion",
        "edges",
        "actions",
        "variables",
        "billable_action_types",
        "email_sending_paused_at",
        "email_sending_paused_reason",
        "email_sending_resumed_at",
    )

    @admin.display(description="Team")
    def team_link(self, hog_flow: HogFlow):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[hog_flow.team.pk]),
            hog_flow.team.name,
        )

    @admin.display(description="Email sending")
    def email_sending_state(self, hog_flow: HogFlow):
        if hog_flow.email_sending_paused_at is None:
            return "Sending"
        return format_html('<span style="color: #C0392B;">Paused {}</span>', hog_flow.email_sending_paused_at)

    @admin.action(description="Pause workflow email sending")
    def pause_email_sending(self, request: HttpRequest, queryset: QuerySet[HogFlow]) -> None:
        paused = 0
        for hog_flow in queryset.filter(email_sending_paused_at__isnull=True):
            if pause_workflow_email_sending(
                team_id=hog_flow.team_id,
                hog_flow_id=str(hog_flow.id),
                hog_flow_name=hog_flow.name or "",
                reason=STAFF_PAUSE_REASON,
                paused_by=PAUSED_BY_STAFF,
            ):
                paused += 1
                logger.warning(
                    "admin_pause_workflow_email_sending",
                    team_id=hog_flow.team_id,
                    hog_flow_id=str(hog_flow.id),
                    triggered_by=getattr(request.user, "email", None),
                )
                # Durable audit trail in the object's admin history: the bulk action bypasses
                # save_model, so without this the acting staff user is recorded only in the log
                # aggregator, not anywhere an audit view can show.
                self.log_change(request, hog_flow, "Paused email sending")
        self.message_user(
            request,
            f"Paused email sending for {paused} workflow(s). Workers pick this up within a few minutes; "
            "the project's admins have been notified. Only staff can resume a staff pause.",
            level=messages.WARNING if paused else messages.INFO,
        )

    @admin.action(description="Resume workflow email sending")
    def resume_email_sending(self, request: HttpRequest, queryset: QuerySet[HogFlow]) -> None:
        resumed = 0
        for hog_flow in queryset.filter(email_sending_paused_at__isnull=False):
            if resume_workflow_email_sending(hog_flow, actor=PAUSED_BY_STAFF):
                resumed += 1
                logger.info(
                    "admin_resume_workflow_email_sending",
                    team_id=hog_flow.team_id,
                    hog_flow_id=str(hog_flow.id),
                    triggered_by=getattr(request.user, "email", None),
                )
                self.log_change(request, hog_flow, "Resumed email sending")
        self.message_user(
            request,
            f"Resumed email sending for {resumed} workflow(s). The detector re-arms, so a workflow that is "
            "still generating complaints or hard bounces pauses again on its own.",
            level=messages.SUCCESS if resumed else messages.INFO,
        )
