import logging
from typing import Any

from django import forms
from django.contrib import admin, messages
from django.http import HttpRequest

from products.mcp_store.backend.models import MCPServerTemplate
from products.mcp_store.backend.oauth import discover_oauth_metadata

logger = logging.getLogger(__name__)


class MCPServerTemplateAdminForm(forms.ModelForm):
    """Separate plain-text inputs for client_id / client_secret so operators can
    paste credentials from the provider's dev portal. Values are merged into the
    encrypted `oauth_credentials` JSON on save; the raw JSON field is never
    exposed in the admin form."""

    client_id = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))
    client_secret = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = MCPServerTemplate
        fields = (
            "name",
            "url",
            "description",
            "auth_type",
            "icon_key",
            "oauth_issuer_url",
            "oauth_metadata",
            "is_active",
        )

    def save(self, commit: bool = True) -> MCPServerTemplate:
        instance: MCPServerTemplate = super().save(commit=False)
        existing_creds = dict(instance.oauth_credentials or {})
        client_id = self.cleaned_data.get("client_id") or ""
        client_secret = self.cleaned_data.get("client_secret") or ""
        if client_id:
            existing_creds["client_id"] = client_id
        if client_secret:
            existing_creds["client_secret"] = client_secret
        instance.oauth_credentials = existing_creds
        if commit:
            instance.save()
        return instance


class MCPServerTemplateAdmin(admin.ModelAdmin):
    form = MCPServerTemplateAdminForm
    list_display = ("name", "url", "auth_type", "has_client_id", "has_metadata", "is_active", "updated_at")
    list_filter = ("auth_type", "is_active", "created_at", "updated_at")
    search_fields = ("name", "url")
    actions = ("activate_templates", "deactivate_templates", "discover_metadata")

    @admin.display(boolean=True, description="Has client_id")
    def has_client_id(self, obj: MCPServerTemplate) -> bool:
        return bool((obj.oauth_credentials or {}).get("client_id"))

    @admin.display(boolean=True, description="Has metadata")
    def has_metadata(self, obj: MCPServerTemplate) -> bool:
        return bool(obj.oauth_metadata)

    @admin.action(description="Mark selected templates active")
    def activate_templates(self, request: HttpRequest, queryset: Any) -> None:
        queryset.update(is_active=True)

    @admin.action(description="Mark selected templates inactive")
    def deactivate_templates(self, request: HttpRequest, queryset: Any) -> None:
        queryset.update(is_active=False)

    @admin.action(description="Discover OAuth metadata from server URL")
    def discover_metadata(self, request: HttpRequest, queryset: Any) -> None:
        ok, failed = 0, 0
        for template in queryset:
            try:
                metadata = discover_oauth_metadata(template.url)
                template.oauth_metadata = metadata
                if issuer := metadata.get("issuer"):
                    template.oauth_issuer_url = issuer
                template.save(update_fields=["oauth_metadata", "oauth_issuer_url", "updated_at"])
                ok += 1
            except Exception as e:
                logger.exception("oauth metadata discovery failed for template %s", template.id)
                messages.warning(request, f"{template.name}: {type(e).__name__}: {e}")
                failed += 1
        if ok:
            messages.success(request, f"Discovered metadata for {ok} template(s)")
        if failed:
            messages.error(request, f"Discovery failed for {failed} template(s) — paste oauth_metadata manually")
