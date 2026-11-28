from typing import Any

from django import forms
from django.contrib import admin

from .logic.seasonal_checklist import InvalidActionSettings, parse_action_settings
from .models import SeasonalCampaign, SeasonalCampaignItem


class SeasonalCampaignItemForm(forms.ModelForm):
    class Meta:
        model = SeasonalCampaignItem
        fields = ("order", "key", "title", "description", "icon", "action_kind", "action_settings")

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        kind = cleaned.get("action_kind")
        if kind:
            try:
                parse_action_settings(kind, cleaned.get("action_settings") or {})
            except InvalidActionSettings as error:
                self.add_error("action_settings", str(error))
        return cleaned


class SeasonalCampaignItemInline(admin.StackedInline):
    model = SeasonalCampaignItem
    form = SeasonalCampaignItemForm
    extra = 0
    ordering = ("order",)


@admin.register(SeasonalCampaign)
class SeasonalCampaignAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "is_active", "starts_at", "ends_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("key", "title")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (SeasonalCampaignItemInline,)
    fieldsets = (
        (None, {"fields": ("key", "is_active", "starts_at", "ends_at")}),
        ("Copy", {"fields": ("title", "description", "reason", "badge", "bubble", "done_title", "done_description")}),
        ("Decorations", {"fields": ("accessories", "snow", "lights")}),
        ("History", {"fields": ("created_at", "updated_at")}),
    )
