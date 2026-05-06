"""
Django admin for visual_review.

Tables here can grow large — RunSnapshot in particular gets one row per
captured screenshot per run, and Artifact stores every distinct image hash
ever seen. The admin classes below are tuned accordingly:

- `show_full_result_count = False` everywhere, plus `NoCountPaginator` on the
  hot tables — Django's default would `COUNT(*)` the full table on every page
  load.
- FKs to high-cardinality tables (Repo, Run, Artifact) use `raw_id_fields`
  rather than the default `<select>` widget that loads every row of the
  target table per change-page render.
- `list_select_related` is set so list views don't N+1 across FKs.
- Read-only by default — these rows are written by ingestion / diff
  pipelines and should not be hand-edited.

Registration: this module deliberately does not use `@admin.register(...)`.
visual_review is an isolated product (per `tach.toml` interfaces), and the
central admin wiring in `posthog/admin/__init__.py` discovers this module via
`importlib.import_module(string)` and reads `ADMIN_REGISTRATIONS` to do the
`admin.site.register(...)` calls itself. Going through `admin.site` from this
side rather than the decorator avoids the django.contrib.admin.sites.site /
package re-export mismatch that breaks `patch.object(admin, "site", ...)` in
`posthog/admin/test_admin.py`.
"""

from typing import Any

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.admin.paginators.no_count_paginator import NoCountPaginator

from .models import Artifact, QuarantinedIdentifier, Repo, Run, RunSnapshot, ToleratedHash


def _team_link(team_id: int | None) -> str | SafeString:
    if team_id is None:
        return "—"
    url = reverse("admin:posthog_team_change", args=[team_id])
    return format_html('<a href="{}">{}</a>', url, team_id)


def _short(value: str | None, length: int = 12) -> str:
    if not value:
        return "—"
    if len(value) <= length:
        return value
    return f"{value[:length]}…"


@admin.register(Repo)
class RepoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "repo_full_name",
        "repo_external_id",
        "team_link",
        "enable_pr_comments",
        "created_at",
        "updated_at",
    )
    list_display_links = ("id", "repo_full_name")
    list_filter = ("enable_pr_comments", "created_at")
    search_fields = ("id", "repo_full_name", "repo_external_id", "team_id")
    ordering = ("-created_at",)
    show_full_result_count = False

    readonly_fields = (
        "id",
        "team_id",
        "repo_external_id",
        "repo_full_name",
        "created_at",
        "updated_at",
        # signing_keys are secret material — never display in admin.
        "signing_keys_summary",
    )
    fieldsets = (
        (None, {"fields": ("id", "team_id", "repo_external_id", "repo_full_name")}),
        ("Configuration", {"fields": ("baseline_file_paths", "enable_pr_comments")}),
        ("Security", {"fields": ("signing_keys_summary",)}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Repo | None = None) -> bool:
        return False

    @admin.display(description="Team", ordering="team_id")
    def team_link(self, repo: Repo) -> str | SafeString:
        return _team_link(repo.team_id)

    @admin.display(description="Signing keys")
    def signing_keys_summary(self, repo: Repo) -> str:
        keys = repo.signing_keys or {}
        if not keys:
            return "(none — auto-generated on first use)"
        return f"{len(keys)} key(s); active kid: {max(keys)}"


class ArtifactAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "content_hash_short",
        "repo_link",
        "team_link",
        "width",
        "height",
        "size_bytes",
        "created_at",
    )
    list_display_links = ("id", "content_hash_short")
    search_fields = ("id", "content_hash", "storage_path", "repo__repo_full_name")
    ordering = ("-created_at",)
    show_full_result_count = False
    paginator = NoCountPaginator
    list_select_related = ("repo",)
    raw_id_fields = ("repo", "thumbnail")
    readonly_fields = (
        "id",
        "team_id",
        "content_hash",
        "storage_path",
        "width",
        "height",
        "size_bytes",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Artifact | None = None) -> bool:
        return False

    @admin.display(description="Hash", ordering="content_hash")
    def content_hash_short(self, artifact: Artifact) -> str:
        return _short(artifact.content_hash)

    @admin.display(description="Repo", ordering="repo__repo_full_name")
    def repo_link(self, artifact: Artifact) -> str | SafeString:
        if artifact.repo_id is None:
            return "—"
        url = reverse("admin:visual_review_repo_change", args=[artifact.repo_id])
        return format_html('<a href="{}">{}</a>', url, artifact.repo.repo_full_name)

    @admin.display(description="Team", ordering="team_id")
    def team_link(self, artifact: Artifact) -> str | SafeString:
        return _team_link(artifact.team_id)


class RunSnapshotInline(admin.TabularInline):
    """
    Inline preview of a run's snapshots. Capped at the first 25 rows via
    `get_queryset` — a single run can have thousands of snapshots, and
    rendering them all would dominate the change page.
    """

    model = RunSnapshot
    fk_name = "run"
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        "identifier",
        "result",
        "review_state",
        "change_kind",
        "diff_percentage",
        "ssim_score",
        "is_quarantined",
    )
    readonly_fields = fields
    # FKs on RunSnapshot point at high-cardinality Artifact rows; force raw_id
    # widgets so the inline doesn't render giant <select>s per row.
    raw_id_fields = ("current_artifact", "baseline_artifact", "diff_artifact", "tolerated_hash_match")

    INLINE_LIMIT = 25

    def get_queryset(self, request: HttpRequest) -> QuerySet[RunSnapshot]:
        qs = super().get_queryset(request).order_by("-created_at")
        # Slicing a QuerySet inside the admin is normally fragile, but the
        # inline only iterates — it doesn't try to count or paginate.
        return qs[: self.INLINE_LIMIT]

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class RunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "repo_link",
        "team_link",
        "status",
        "run_type",
        "purpose",
        "review_decision",
        "branch",
        "pr_number",
        "commit_short",
        "total_snapshots",
        "changed_count",
        "is_superseded",
        "created_at",
    )
    list_display_links = ("id",)
    list_filter = ("status", "run_type", "purpose", "review_decision", "approved")
    search_fields = (
        "id",
        "commit_sha",
        "branch",
        "pr_number",
        "repo__repo_full_name",
        "team_id",
    )
    ordering = ("-created_at",)
    show_full_result_count = False
    paginator = NoCountPaginator
    list_select_related = ("repo",)
    raw_id_fields = ("repo", "superseded_by")

    readonly_fields = (
        "id",
        "team_id",
        "repo",
        "status",
        "run_type",
        "purpose",
        "review_decision",
        "approved",
        "approved_at",
        "approved_by_link",
        "commit_sha",
        "branch",
        "pr_number",
        "total_snapshots",
        "changed_count",
        "new_count",
        "removed_count",
        "tolerated_match_count",
        "error_message",
        "superseded_by",
        "metadata",
        "created_at",
        "completed_at",
    )
    fieldsets = (
        (None, {"fields": ("id", "team_id", "repo", "status", "run_type", "purpose")}),
        (
            "Review",
            {
                "fields": (
                    "review_decision",
                    "approved",
                    "approved_at",
                    "approved_by_link",
                )
            },
        ),
        (
            "Git context",
            {"fields": ("commit_sha", "branch", "pr_number", "superseded_by")},
        ),
        (
            "Counts",
            {
                "fields": (
                    "total_snapshots",
                    "changed_count",
                    "new_count",
                    "removed_count",
                    "tolerated_match_count",
                )
            },
        ),
        ("Errors & metadata", {"fields": ("error_message", "metadata")}),
        ("Dates", {"fields": ("created_at", "completed_at")}),
    )
    inlines = [RunSnapshotInline]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Run | None = None) -> bool:
        return False

    @admin.display(description="Repo", ordering="repo__repo_full_name")
    def repo_link(self, run: Run) -> str | SafeString:
        if run.repo_id is None:
            return "—"
        url = reverse("admin:visual_review_repo_change", args=[run.repo_id])
        return format_html('<a href="{}">{}</a>', url, run.repo.repo_full_name)

    @admin.display(description="Team", ordering="team_id")
    def team_link(self, run: Run) -> str | SafeString:
        return _team_link(run.team_id)

    @admin.display(description="Commit", ordering="commit_sha")
    def commit_short(self, run: Run) -> str:
        return _short(run.commit_sha, 7)

    @admin.display(description="Superseded", boolean=True)
    def is_superseded(self, run: Run) -> bool:
        return run.superseded_by_id is not None

    @admin.display(description="Approved by")
    def approved_by_link(self, run: Run) -> str | SafeString:
        # `approved_by_id` is a plain BigIntegerField — no FK to keep cross-DB
        # compat. Build the admin link by hand.
        if run.approved_by_id is None:
            return "—"
        url = reverse("admin:posthog_user_change", args=[run.approved_by_id])
        return format_html('<a href="{}">{}</a>', url, run.approved_by_id)


class RunSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "identifier_short",
        "run_link",
        "team_link",
        "result",
        "change_kind",
        "review_state",
        "is_quarantined",
        "diff_percentage",
        "ssim_score",
        "created_at",
    )
    list_display_links = ("id", "identifier_short")
    list_filter = ("result", "review_state", "change_kind", "is_quarantined")
    search_fields = (
        "id",
        "identifier",
        "current_hash",
        "baseline_hash",
        "run__id",
        "run__repo__repo_full_name",
    )
    ordering = ("-created_at",)
    show_full_result_count = False
    paginator = NoCountPaginator
    list_select_related = ("run", "run__repo")
    raw_id_fields = (
        "run",
        "current_artifact",
        "baseline_artifact",
        "diff_artifact",
        "tolerated_hash_match",
    )

    readonly_fields = (
        "id",
        "team_id",
        "run",
        "identifier",
        "current_hash",
        "baseline_hash",
        "current_width",
        "current_height",
        "result",
        "classification_reason",
        "tolerated_hash_match",
        "is_quarantined",
        "diff_percentage",
        "diff_pixel_count",
        "ssim_score",
        "change_kind",
        "diff_metadata",
        "review_state",
        "reviewed_at",
        "reviewed_by_link",
        "review_comment",
        "approved_hash",
        "metadata",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("id", "team_id", "run", "identifier")}),
        (
            "Hashes & dimensions",
            {
                "fields": (
                    "current_hash",
                    "baseline_hash",
                    "approved_hash",
                    "current_width",
                    "current_height",
                )
            },
        ),
        (
            "Artifacts",
            {"fields": ("current_artifact", "baseline_artifact", "diff_artifact")},
        ),
        (
            "Classification",
            {
                "fields": (
                    "result",
                    "classification_reason",
                    "tolerated_hash_match",
                    "is_quarantined",
                    "change_kind",
                    "diff_percentage",
                    "diff_pixel_count",
                    "ssim_score",
                    "diff_metadata",
                )
            },
        ),
        (
            "Review",
            {
                "fields": (
                    "review_state",
                    "reviewed_at",
                    "reviewed_by_link",
                    "review_comment",
                )
            },
        ),
        ("Metadata", {"fields": ("metadata",)}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: RunSnapshot | None = None) -> bool:
        return False

    @admin.display(description="Identifier", ordering="identifier")
    def identifier_short(self, snapshot: RunSnapshot) -> str:
        return _short(snapshot.identifier, 60)

    @admin.display(description="Run", ordering="run__created_at")
    def run_link(self, snapshot: RunSnapshot) -> str | SafeString:
        if snapshot.run_id is None:
            return "—"
        url = reverse("admin:visual_review_run_change", args=[snapshot.run_id])
        return format_html('<a href="{}">{}</a>', url, snapshot.run_id)

    @admin.display(description="Team", ordering="team_id")
    def team_link(self, snapshot: RunSnapshot) -> str | SafeString:
        return _team_link(snapshot.team_id)

    @admin.display(description="Reviewed by")
    def reviewed_by_link(self, snapshot: RunSnapshot) -> str | SafeString:
        if snapshot.reviewed_by_id is None:
            return "—"
        url = reverse("admin:posthog_user_change", args=[snapshot.reviewed_by_id])
        return format_html('<a href="{}">{}</a>', url, snapshot.reviewed_by_id)


class ToleratedHashAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "identifier_short",
        "repo_link",
        "team_link",
        "reason",
        "baseline_hash_short",
        "alternate_hash_short",
        "diff_percentage",
        "expires_at",
        "created_at",
    )
    list_display_links = ("id",)
    list_filter = ("reason", "created_at")
    search_fields = (
        "id",
        "identifier",
        "baseline_hash",
        "alternate_hash",
        "repo__repo_full_name",
    )
    ordering = ("-created_at",)
    show_full_result_count = False
    paginator = NoCountPaginator
    list_select_related = ("repo", "source_run")
    raw_id_fields = ("repo", "source_run")

    readonly_fields = (
        "id",
        "team_id",
        "repo",
        "identifier",
        "baseline_hash",
        "alternate_hash",
        "reason",
        "source_run",
        "created_by_link",
        "diff_percentage",
        "created_at",
        "expires_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.display(description="Identifier", ordering="identifier")
    def identifier_short(self, hash_obj: ToleratedHash) -> str:
        return _short(hash_obj.identifier, 60)

    @admin.display(description="Baseline", ordering="baseline_hash")
    def baseline_hash_short(self, hash_obj: ToleratedHash) -> str:
        return _short(hash_obj.baseline_hash)

    @admin.display(description="Alternate", ordering="alternate_hash")
    def alternate_hash_short(self, hash_obj: ToleratedHash) -> str:
        return _short(hash_obj.alternate_hash)

    @admin.display(description="Repo", ordering="repo__repo_full_name")
    def repo_link(self, hash_obj: ToleratedHash) -> str | SafeString:
        if hash_obj.repo_id is None:
            return "—"
        url = reverse("admin:visual_review_repo_change", args=[hash_obj.repo_id])
        return format_html('<a href="{}">{}</a>', url, hash_obj.repo.repo_full_name)

    @admin.display(description="Team", ordering="team_id")
    def team_link(self, hash_obj: ToleratedHash) -> str | SafeString:
        return _team_link(hash_obj.team_id)

    @admin.display(description="Created by")
    def created_by_link(self, hash_obj: ToleratedHash) -> str | SafeString:
        if hash_obj.created_by_id is None:
            return "—"
        url = reverse("admin:posthog_user_change", args=[hash_obj.created_by_id])
        return format_html('<a href="{}">{}</a>', url, hash_obj.created_by_id)


class QuarantinedIdentifierAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "identifier_short",
        "repo_link",
        "team_link",
        "run_type",
        "source",
        "reason_preview",
        "expires_at",
        "created_at",
    )
    list_display_links = ("id",)
    list_filter = ("source", "run_type", "created_at")
    search_fields = (
        "id",
        "identifier",
        "reason",
        "repo__repo_full_name",
    )
    ordering = ("-created_at",)
    show_full_result_count = False
    list_select_related = ("repo",)
    raw_id_fields = ("repo",)

    readonly_fields = (
        "id",
        "team_id",
        "repo",
        "identifier",
        "run_type",
        "reason",
        "source",
        "expires_at",
        "created_by_link",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Identifier", ordering="identifier")
    def identifier_short(self, q: QuarantinedIdentifier) -> str:
        return _short(q.identifier, 60)

    @admin.display(description="Reason")
    def reason_preview(self, q: QuarantinedIdentifier) -> str:
        return _short(q.reason, 60)

    @admin.display(description="Repo", ordering="repo__repo_full_name")
    def repo_link(self, q: QuarantinedIdentifier) -> str | SafeString:
        if q.repo_id is None:
            return "—"
        url = reverse("admin:visual_review_repo_change", args=[q.repo_id])
        return format_html('<a href="{}">{}</a>', url, q.repo.repo_full_name)

    @admin.display(description="Team", ordering="team_id")
    def team_link(self, q: QuarantinedIdentifier) -> str | SafeString:
        return _team_link(q.team_id)

    @admin.display(description="Created by")
    def created_by_link(self, q: QuarantinedIdentifier) -> str | SafeString:
        if q.created_by_id is None:
            return "—"
        url = reverse("admin:posthog_user_change", args=[q.created_by_id])
        return format_html('<a href="{}">{}</a>', url, q.created_by_id)


# Read by `posthog.admin._import_self_registering_product_admins`. Order is
# preserved as the registration order, which determines admin sidebar order.
ADMIN_REGISTRATIONS: tuple[tuple[type, type[admin.ModelAdmin]], ...] = (
    (Repo, RepoAdmin),
    (Artifact, ArtifactAdmin),
    (Run, RunAdmin),
    (RunSnapshot, RunSnapshotAdmin),
    (ToleratedHash, ToleratedHashAdmin),
    (QuarantinedIdentifier, QuarantinedIdentifierAdmin),
)
