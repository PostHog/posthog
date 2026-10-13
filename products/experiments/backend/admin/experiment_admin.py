import copy
from uuid import UUID

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.models.organization import Organization

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.admin.recalculation_panel import (
    build_recalculation_panel,
    start_recalculation_for_experiment,
)
from products.experiments.backend.legacy_migration import migrate_experiment as migrate_legacy_experiment
from products.experiments.backend.models.experiment import Experiment, ExperimentHoldout, ExperimentMetricsRecalculation
from products.experiments.backend.recalculation import get_latest_recalculation
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


def has_legacy_metric(metrics):
    if not metrics:
        return False
    for metric in metrics:
        kind = metric.get("kind")
        if kind in ("ExperimentFunnelsQuery", "ExperimentTrendsQuery"):
            return True
    return False


def _is_malformed_properties(properties):
    """Check if properties are in old-style dict format instead of list format."""
    if properties is None or isinstance(properties, list):
        return False
    if isinstance(properties, dict):
        if "AND" in properties or "OR" in properties or "type" in properties:
            return False
        if len(properties) > 0:
            return True
    return False


def has_malformed_properties(metrics):
    """Check if any metric has dict-style properties instead of list format."""
    if not metrics:
        return False
    for metric in metrics:
        for step in metric.get("series", []):
            if _is_malformed_properties(step.get("properties")):
                return True
        source = metric.get("source")
        if isinstance(source, dict) and _is_malformed_properties(source.get("properties")):
            return True
        for field in ["numerator", "denominator", "start_event", "completion_event"]:
            node = metric.get(field)
            if isinstance(node, dict) and _is_malformed_properties(node.get("properties")):
                return True
    return False


def transform_old_style_properties(properties):
    """Convert old-style dict properties to list format."""
    if properties is None or isinstance(properties, list):
        return properties
    if isinstance(properties, dict):
        if "AND" in properties or "OR" in properties or "type" in properties:
            return properties
        if len(properties) > 0:
            result = []
            for key, value in properties.items():
                key_parts = key.rsplit("__", 1)
                result.append(
                    {
                        "key": key_parts[0],
                        "value": value,
                        "operator": key_parts[1] if len(key_parts) > 1 else "exact",
                        "type": "event",
                    }
                )
            return result
    return properties


def fix_metric_properties(metric):
    """Transform old-style properties in all metric fields."""
    if not metric:
        return metric
    for step in metric.get("series", []):
        if "properties" in step:
            step["properties"] = transform_old_style_properties(step.get("properties"))
    if "source" in metric and isinstance(metric.get("source"), dict):
        if "properties" in metric["source"]:
            metric["source"]["properties"] = transform_old_style_properties(metric["source"]["properties"])
    for field in ["numerator", "denominator", "start_event", "completion_event"]:
        if field in metric and isinstance(metric.get(field), dict):
            if "properties" in metric[field]:
                metric[field]["properties"] = transform_old_style_properties(metric[field]["properties"])
    return metric


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
        all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
        if has_malformed_properties(all_metrics):
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
        all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
        if has_legacy_metric(all_metrics):
            return format_html('<span style="color: orange;">Legacy</span>')
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

    change_form_template = "admin/posthog/experiment/change_form.html"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}

        obj = self.get_object(request, object_id)
        if obj is None:
            messages.error(request, "Experiment not found")
            return redirect("admin:experiments_experiment_changelist")

        all_metrics = (obj.metrics or []) + (obj.metrics_secondary or [])
        extra_context["show_fix_properties"] = has_malformed_properties(all_metrics)

        # Get all related ExperimentSavedMetric objects
        shared_metrics = obj.saved_metrics.all()
        shared_metrics_status = []
        has_legacy_shared_metric = False
        has_unmigrated_legacy_shared_metric = False
        for metric in shared_metrics:
            kind = metric.query.get("kind") if metric.query else None
            is_legacy = kind in ("ExperimentFunnelsQuery", "ExperimentTrendsQuery")
            if is_legacy:
                has_legacy_shared_metric = True
            migrated_to_id = metric.metadata.get("migrated_to") if metric.metadata else None
            migrated = migrated_to_id is not None
            if is_legacy and not migrated:
                has_unmigrated_legacy_shared_metric = True
            shared_metrics_status.append(
                {
                    "id": metric.id,
                    "name": metric.name,
                    "is_legacy": is_legacy,
                    "migrated": migrated,
                    "migrate_url": reverse("admin:experiments_experimentsavedmetric_change", args=[metric.id]),
                    "migrated_to_id": migrated_to_id,
                    "migrated_to_url": reverse("admin:experiments_experimentsavedmetric_change", args=[migrated_to_id])
                    if migrated_to_id
                    else None,
                }
            )
        extra_context["shared_metrics_status"] = shared_metrics_status
        extra_context["show_migration"] = has_legacy_metric(all_metrics) or has_legacy_shared_metric
        extra_context["can_migrate"] = not has_unmigrated_legacy_shared_metric

        latest_recalculation = get_latest_recalculation(obj)
        extra_context["recalculation_panel"] = (
            build_recalculation_panel(latest_recalculation) if latest_recalculation is not None else None
        )
        # request_recalculation rejects an experiment with no start_date, so a draft gets no button.
        extra_context["can_start_recalculation"] = obj.is_launched and self.has_change_permission(request, obj)
        extra_context["start_recalculation_url"] = reverse("admin:experiment_start_recalculation", args=[obj.pk])

        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/migrate/",
                self.admin_site.admin_view(self.migrate_experiment),
                name="experiment_migrate",
            ),
            path(
                "<path:object_id>/fix-properties/",
                self.admin_site.admin_view(self.fix_malformed_properties),
                name="experiment_fix_properties",
            ),
            path(
                "<path:object_id>/start-recalculation/",
                self.admin_site.admin_view(self.start_recalculation_view),
                name="experiment_start_recalculation",
            ),
        ]
        return custom_urls + urls

    def start_recalculation_view(self, request: HttpRequest, object_id: str) -> HttpResponseRedirect:
        experiment = self.get_object(request, object_id)
        if experiment is None:
            messages.error(request, "Experiment not found")
            return HttpResponseRedirect(reverse("admin:experiments_experiment_changelist"))

        # admin_view only enforces is_staff; a view-only staff user must not be able to start a run.
        if not self.has_change_permission(request, experiment):
            raise PermissionDenied

        change_url = reverse("admin:experiments_experiment_change", args=[experiment.pk])
        if request.method != "POST":
            return HttpResponseRedirect(change_url)

        return start_recalculation_for_experiment(
            request, experiment, trigger=ExperimentMetricsRecalculation.Trigger.MANUAL, fallback_url=change_url
        )

    def migrate_experiment(self, request, object_id):
        try:
            # nosemgrep: idor-lookup-without-team (Django admin, staff-only)
            team_id = Experiment.objects.values_list("team_id", flat=True).get(pk=object_id)
            migration = migrate_legacy_experiment(int(object_id), team_id)

            if migration.already_migrated:
                messages.warning(request, f"Experiment already migrated to {migration.experiment.id}")
            else:
                messages.success(request, "Experiment migrated successfully")
            return redirect("admin:experiments_experiment_change", migration.experiment.pk)
        except Experiment.DoesNotExist:
            messages.error(request, "Experiment not found")
            return redirect("admin:experiments_experiment_changelist")
        except Exception as e:
            messages.error(request, f"Error migrating experiment: {e}")
            return redirect("admin:experiments_experiment_change", object_id)

    def fix_malformed_properties(self, request, object_id):
        try:
            # nosemgrep: idor-lookup-without-team (Django admin, staff-only)
            experiment = Experiment.objects.get(pk=object_id)

            all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
            if not has_malformed_properties(all_metrics):
                messages.info(request, "No malformed properties found")
                return redirect("admin:experiments_experiment_change", object_id)

            # Fix metrics
            if experiment.metrics:
                experiment.metrics = [fix_metric_properties(copy.deepcopy(m)) for m in experiment.metrics]
            if experiment.metrics_secondary:
                experiment.metrics_secondary = [
                    fix_metric_properties(copy.deepcopy(m)) for m in experiment.metrics_secondary
                ]

            experiment.save(update_fields=["metrics", "metrics_secondary"])
            messages.success(request, "Fixed malformed properties in experiment metrics")
            return redirect("admin:experiments_experiment_change", object_id)
        except Experiment.DoesNotExist:
            messages.error(request, "Experiment not found")
            return redirect("admin:experiments_experiment_changelist")
        except Exception as e:
            messages.error(request, f"Error fixing properties: {e}")
            return redirect("admin:experiments_experiment_change", object_id)

    @admin.action(description="Fix malformed metric properties")
    def fix_malformed_properties_bulk(self, request, queryset):
        fixed_count = 0
        skipped_count = 0

        for experiment in queryset:
            all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
            if not has_malformed_properties(all_metrics):
                skipped_count += 1
                continue

            if experiment.metrics:
                experiment.metrics = [fix_metric_properties(copy.deepcopy(m)) for m in experiment.metrics]
            if experiment.metrics_secondary:
                experiment.metrics_secondary = [
                    fix_metric_properties(copy.deepcopy(m)) for m in experiment.metrics_secondary
                ]

            experiment.save(update_fields=["metrics", "metrics_secondary"])
            fixed_count += 1

        if fixed_count > 0:
            messages.success(request, f"Fixed malformed properties in {fixed_count} experiment(s)")
        if skipped_count > 0:
            messages.info(request, f"Skipped {skipped_count} experiment(s) with no malformed properties")
