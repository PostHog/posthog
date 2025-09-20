from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models.link import Link


class LinkAdmin(admin.ModelAdmin):
    list_display = ("id", "redirect_url_display", "team_link", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at")
    search_fields = ("id", "redirect_url", "team__name")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("team",)
    fieldsets = (
        (None, {"fields": ("id", "redirect_url", "short_link_domain", "short_code", "team")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
        ("Additional Info", {"fields": ("description",)}),
    )

    def redirect_url_display(self, obj: Link):
        return format_html('<a href="{}" target="_blank">{}</a>', obj.redirect_url, obj.redirect_url)

    def team_link(self, obj: Link):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[obj.team.pk]),
            obj.team.name,
        )
