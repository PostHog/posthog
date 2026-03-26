from django.contrib import admin

from .models import CodeInviteRedemption


class TaskAdmin(admin.ModelAdmin):
    list_display = ("slug", "title", "origin_product", "team", "created_by", "created_at", "deleted")
    list_filter = ("origin_product", "deleted", "created_at")
    search_fields = ("title", "description", "repository")
    readonly_fields = ("id", "slug", "task_number", "created_at", "updated_at", "deleted_at")

    fieldsets = (
        (None, {"fields": ("id", "slug", "task_number", "title", "description", "origin_product")}),
        ("Team & User", {"fields": ("team", "created_by")}),
        ("Repository", {"fields": ("github_integration", "repository")}),
        ("Schema", {"fields": ("json_schema",)}),
        ("Status", {"fields": ("deleted", "deleted_at")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )


class TaskRunAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "status", "environment", "stage", "created_at")
    list_filter = ("status", "environment", "created_at")
    search_fields = ("task__title", "branch", "stage")
    readonly_fields = ("id", "created_at", "updated_at", "completed_at")

    fieldsets = (
        (None, {"fields": ("id", "task", "status", "environment", "stage", "branch")}),
        ("Storage", {"fields": ("error_message",)}),
        ("Data", {"fields": ("output", "state")}),
        ("Dates", {"fields": ("created_at", "updated_at", "completed_at")}),
    )


class SandboxSnapshotAdmin(admin.ModelAdmin):
    list_display = ("external_id", "status", "created_at", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("external_id", "repos")
    readonly_fields = ("id", "external_id", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("id", "external_id", "status")}),
        ("Repository Info", {"fields": ("repos",)}),
        ("Metadata", {"fields": ("metadata",)}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )


class CodeInviteRedemptionInline(admin.TabularInline):
    model = CodeInviteRedemption
    extra = 0
    can_delete = False
    readonly_fields = ("id", "user", "organization", "redeemed_at")


class CodeInviteAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "description",
        "is_active",
        "redemption_count",
        "max_redemptions",
        "expires_at",
        "created_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("code", "description")
    readonly_fields = ("id", "redemption_count", "created_at")
    inlines = []

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("id", "code", "redemption_count", "created_at")
        return ("id", "redemption_count", "created_at")

    def get_fieldsets(self, request, obj=None):
        if obj:
            # Show auto-generated code as readonly on existing records
            return (
                (None, {"fields": ("id", "code", "description")}),
                ("Limits", {"fields": ("is_active", "max_redemptions", "redemption_count", "expires_at")}),
                ("Metadata", {"fields": ("created_by", "created_at")}),
            )
        # On add, omit code — it will be auto-generated on save
        return (
            (None, {"fields": ("id", "description")}),
            ("Limits", {"fields": ("is_active", "max_redemptions", "expires_at")}),
            ("Metadata", {"fields": ("created_by",)}),
        )

    def get_inlines(self, request, obj=None):
        return [CodeInviteRedemptionInline]


class CodeInviteRedemptionAdmin(admin.ModelAdmin):
    list_display = ("invite_code", "user", "organization", "redeemed_at")
    list_filter = ("redeemed_at",)
    search_fields = ("user__email", "invite_code__code")
    readonly_fields = ("id", "invite_code", "user", "organization", "redeemed_at")
