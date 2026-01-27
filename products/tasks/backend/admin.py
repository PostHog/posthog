from django.contrib import admin


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
