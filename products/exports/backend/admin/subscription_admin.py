from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.admin.paginators.no_count_paginator import NoCountPaginator

from products.exports.backend.models.subscription import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    show_full_result_count = False
    paginator = NoCountPaginator

    list_display = (
        "id",
        "title",
        "team_link",
        "target_type",
        "frequency",
        "enabled",
        "deleted",
        "next_delivery_date",
        "created_at",
    )
    list_display_links = ("id", "title")
    list_select_related = ("team", "team__organization")
    list_filter = ("target_type", "frequency", "enabled", "deleted")
    search_fields = ("id", "title", "team__id", "team__name", "team__organization__name")
    ordering = ("-id",)
    exclude = ("dashboard_export_insights",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Team")
    def team_link(self, subscription: Subscription):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[subscription.team_id]),
            subscription.team.name,
        )
