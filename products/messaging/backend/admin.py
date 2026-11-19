from django.contrib import admin
from django.http import HttpRequest

from products.messaging.backend.models.email_hard_bounce import EmailHardBounce


@admin.register(EmailHardBounce)
class EmailHardBounceAdmin(admin.ModelAdmin):
    list_display = ("email", "first_bounced_at", "last_bounced_at")
    ordering = ("-last_bounced_at",)
    search_fields = ("email",)
    readonly_fields = ("email", "first_bounced_at", "last_bounced_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: EmailHardBounce | None = None) -> bool:
        return False
