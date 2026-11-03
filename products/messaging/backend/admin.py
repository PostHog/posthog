import hashlib

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from products.messaging.backend.models.known_invalid_email_address import KnownInvalidEmailAddress


@admin.register(KnownInvalidEmailAddress)
class KnownInvalidEmailAddressAdmin(admin.ModelAdmin):
    list_display = ("identifier_hash", "first_bounced_at", "last_bounced_at", "last_bounced_team_id")
    ordering = ("-last_bounced_at",)
    search_help_text = "Search by the full email address."
    search_fields = ("identifier_hash",)
    readonly_fields = ("identifier_hash", "first_bounced_at", "last_bounced_at", "last_bounced_team_id")

    def get_search_results(
        self, request: HttpRequest, queryset: QuerySet[KnownInvalidEmailAddress], search_term: str
    ) -> tuple[QuerySet[KnownInvalidEmailAddress], bool]:
        # Rows store only a hash, so hash the searched address the way the Node writer does.
        term = search_term.strip().lower()
        if not term:
            return queryset, False
        return queryset.filter(identifier_hash=hashlib.sha256(term.encode()).hexdigest()), False

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: KnownInvalidEmailAddress | None = None) -> bool:
        return False
