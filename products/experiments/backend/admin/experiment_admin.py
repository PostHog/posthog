from uuid import UUID

from django.contrib import admin, messages
from django.forms import ModelForm
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from posthog.models.organization import Organization

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.models.experiment import Experiment, ExperimentHoldout
from products.experiments.backend.staff_operations import (
    experiment_has_legacy_metric,
    experiment_has_malformed_properties,
    fix_malformed_properties,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class ExperimentAdminForm(ModelForm):
    class Meta:
        model = Experiment
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit the queryset of the exposure_cohort and holdout fields to the team
        # Otherwise, the queryset will fetch _all_ cohorts and holdouts for _all_ teams,
        # which is a lot and quite slow.
        if self.instance and self.instance.pk:
            if "exposure_cohort" in self.fields:
                self.fields["exposure_cohort"].queryset = Cohort.objects.filter(team=self.instance.team)  # type: ignore
            if "holdout" in self.fields:
                self.fields["holdout"].queryset = ExperimentHoldout.objects.filter(team=self.instance.team)  # type: ignore
            if "feature_flag" in self.fields:
                self.fields["feature_flag"].queryset = FeatureFlag.objects_including_soft_deleted.filter(  # type: ignore[attr-defined]
                    team=self.instance.team
                )


class ExperimentStatusFilter(admin.SimpleListFilter):
    title = "status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return [(status.value, status.label) for status in Experiment.Status]

    def queryset(self, request, queryset):
        # Mirrors Experiment.computed_status, so rows whose stored status is still null match too.
        match self.value():
            case Experiment.Status.DRAFT:
                return queryset.filter(start_date__isnull=True)
            case Experiment.Status.RUNNING:
                return queryset.filter(start_date__isnull=False, end_date__isnull=True)
            case Experiment.Status.STOPPED:
                return queryset.filter(start_date__isnull=False, end_date__isnull=False)
        return queryset


class OrganizationFilter(admin.SimpleListFilter):
    # Only the organization named in the URL is offered, because a sidebar that lists every
    # organization loads them all on each changelist render. The organization column sets the URL.
    title = "organization"
    parameter_name = "organization"

    def _organization_id(self) -> UUID | None:
        try:
            return UUID(self.value() or "")
        except ValueError:
            return None

    def lookups(self, request, model_admin):
        organization_id = self._organization_id()
        if organization_id is None:
            return []
        organization = Organization.objects.filter(pk=organization_id).only("name").first()
        return [(str(organization_id), organization.name if organization else str(organization_id))]

    def queryset(self, request, queryset):
        organization_id = self._organization_id()
        if organization_id is None:
            return queryset
        return queryset.filter(team__organization_id=organization_id)


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    form = ExperimentAdminForm
    list_display = (
        "id",
        "name",
        "status_indicator",
        "engine",
        "migrated_links",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    list_filter = (ExperimentStatusFilter, "archived", OrganizationFilter)
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)
    actions = ["fix_malformed_properties_bulk"]
    readonly_fields = ("console_link",)

    @admin.display(description="Team")
    def team_link(self, experiment: Experiment):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[experiment.team.pk]),
            experiment.team.name,
        )

    @admin.display(description="Organization")
    def organization_link(self, experiment: Experiment):
        organization = experiment.team.organization
        return format_html(
            '<a href="{}?organization={}" title="Show only this organization\'s experiments">{}</a>',
            reverse("admin:experiments_experiment_changelist"),
            organization.pk,
            organization.name,
        )

    @admin.display(description="Status")
    def status_indicator(self, experiment: Experiment):
        issues = []
        if experiment_has_malformed_properties(experiment):
            issues.append("malformed properties")
        # Add more issue checks here as needed
        if issues:
            return format_html(
                '<span style="color: #dc3545;" title="{}">⚠️</span>',
                ", ".join(issues),
            )
        return ""

    @admin.display(description="Engine")
    def engine(self, experiment: Experiment):
        if experiment_has_legacy_metric(experiment):
            return mark_safe('<span style="color: orange;">Legacy</span>')
        return ""

    @admin.display(description="")
    def migrated_links(self, experiment: Experiment):
        if experiment.stats_config and "migrated_from" in experiment.stats_config:
            return format_html(
                '<a href="{}">Migrated From: {}</a>',
                reverse("admin:experiments_experiment_change", args=[experiment.stats_config["migrated_from"]]),
                experiment.stats_config["migrated_from"],
            )
        if experiment.stats_config and "migrated_to" in experiment.stats_config:
            return format_html(
                '<a href="{}">Migrated To: {}</a>',
                reverse("admin:experiments_experiment_change", args=[experiment.stats_config["migrated_to"]]),
                experiment.stats_config["migrated_to"],
            )
        return ""

    @admin.display(description="PostHog Admin")
    def console_link(self, experiment: Experiment):
        return format_html(
            '<a href="{}?experiment={}">Repairs, migration and recalculations: now in PostHog Admin &#8599;</a>',
            reverse("admin_console_tool", kwargs={"tool_key": "experiments"}),
            experiment.pk,
        )

    @admin.action(description="Fix malformed metric properties")
    def fix_malformed_properties_bulk(self, request, queryset):
        fixed_count = 0
        skipped_count = 0

        for experiment in queryset:
            if fix_malformed_properties(experiment):
                fixed_count += 1
            else:
                skipped_count += 1

        if fixed_count > 0:
            messages.success(request, f"Fixed malformed properties in {fixed_count} experiment(s)")
        if skipped_count > 0:
            messages.info(request, f"Skipped {skipped_count} experiment(s) with no malformed properties")
