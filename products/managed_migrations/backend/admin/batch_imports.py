from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from products.managed_migrations.backend.models.batch_imports import BatchImport


class BatchImportAdminForm(forms.ModelForm):
    sink_type = forms.ChoiceField(
        choices=[("capture", "Capture"), ("kafka", "Kafka")],
        required=False,
        help_text="Capture sends events via HTTP; Kafka writes directly to Kafka.",
    )
    send_rate = forms.IntegerField(
        required=False,
        help_text="Events per second to send (e.g., 1000). Leave empty to keep current value.",
        widget=forms.NumberInput(attrs={"placeholder": "e.g., 1000"}),
    )

    class Meta:
        model = BatchImport
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.import_config:
            sink = self.instance.import_config.get("sink", {})
            if sink.get("type"):
                self.fields["sink_type"].initial = sink["type"]
            if sink.get("send_rate"):
                self.fields["send_rate"].initial = sink["send_rate"]

    def save(self, commit=True):
        instance = super().save(commit=False)

        sink_type = self.cleaned_data.get("sink_type")
        send_rate = self.cleaned_data.get("send_rate")

        if sink_type:
            if not instance.import_config:
                instance.import_config = {}
            existing_sink = instance.import_config.get("sink", {})
            sink = {
                "type": sink_type,
                "send_rate": send_rate if send_rate is not None else existing_sink.get("send_rate", 1000),
            }
            if sink_type == "kafka":
                sink["topic"] = existing_sink.get("topic", "historical")
                sink["transaction_timeout_seconds"] = existing_sink.get("transaction_timeout_seconds", 60)

            instance.import_config["sink"] = sink

        if commit:
            instance.save()
        return instance


@admin.register(BatchImport)
class BatchImportAdmin(admin.ModelAdmin):
    form = BatchImportAdminForm
    actions = ("resume", "resume_with_inflight_part_reset")
    list_display = (
        "id",
        "team",
        "status",
        "get_progress",
        "backoff_until",
        "created_by_id",
        "created_at",
        "get_sink_type",
        "get_send_rate",
    )
    list_filter = ("status", "created_at")
    search_fields = ("id", "status_message", "team__name")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "state",
        "import_config",
        "display_status_message",
        "lease_id",
        "leased_until",
        "backoff_attempt",
        "backoff_until",
        "get_worker_progress",
    )
    autocomplete_fields = ("team",)
    fieldsets = (
        (None, {"fields": ("team", "created_by_id", "status", "status_message", "display_status_message")}),
        (
            "Worker state",
            {
                "fields": (
                    "get_worker_progress",
                    "lease_id",
                    "leased_until",
                    "backoff_attempt",
                    "backoff_until",
                ),
                "description": (
                    "A paused job keeps its worker lease; both resume actions clear it "
                    "(a bare status change leaves the row unclaimable until the lease expires, "
                    "up to 30 minutes). A running job with a future leased_until is actively "
                    "claimed by a worker. Choosing a resume action: 'Resume (keep progress)' "
                    "continues from the saved byte offset - right for transient pauses and "
                    "for source data that has not changed. 'Resume + re-import in-flight part' "
                    "resets the current part to offset 0 first - right when the source bytes "
                    "changed underneath the saved offset (a re-downloaded nondeterministic "
                    "export, or a source file replaced after a data fix), which typically "
                    "shows up as an 'Invalid JSON syntax' pause. The re-imported overlap "
                    "dedupes for sources with deterministic event UUIDs (Mixpanel $insert_id, "
                    "Amplitude uuid)."
                ),
            },
        ),
        (
            "Sink Configuration",
            {
                "fields": ("sink_type", "send_rate"),
                "description": "Configure the sink type and send rate for this batch import",
            },
        ),
        (
            "Import Configuration",
            {
                "fields": ("import_config",),
                "description": "Full JSON configuration (read-only)",
            },
        ),
        ("Metadata", {"fields": ("id", "created_at", "updated_at", "state")}),
    )

    @admin.display(description="Progress")
    def get_progress(self, obj):
        """Parts done / total, from the worker-owned state JSON."""
        done, total, _inflight = obj.parts_progress()
        if total == 0:
            return "not started"
        return f"{done}/{total} parts"

    @admin.display(description="Worker progress")
    def get_worker_progress(self, obj):
        """Progress summary plus the in-flight part's key and byte offset."""
        done, total, inflight = obj.parts_progress()
        if total == 0:
            return "No part state yet (job has not started)"
        if inflight is None:
            return format_html("<b>{}/{} parts done</b> - all parts complete", done, total)
        return format_html(
            "<b>{}/{} parts done</b><br>In-flight part: <code>{}</code><br>Offset: {} of {} bytes (decompressed)",
            done,
            total,
            inflight.get("key", "?"),
            inflight.get("current_offset", 0),
            inflight.get("total_size") if inflight.get("total_size") is not None else "unknown",
        )

    @admin.action(description="Resume (keep progress) - continue paused import from its saved offset")
    def resume(self, request, queryset):
        """Resume paused jobs from their saved progress: for transient pauses and
        unchanged source data. See the 'Worker state' section on the detail page
        for how this differs from the reset variant."""
        for batch_import in queryset:
            try:
                batch_import.resume_after_pause()
            except ValueError as e:
                self.message_user(request, f"{batch_import.id}: {e}", level=messages.WARNING)
            else:
                self.message_user(
                    request,
                    f"{batch_import.id}: resumed from saved progress",
                    level=messages.SUCCESS,
                )

    @admin.action(
        description="Resume + re-import in-flight part - reset paused import's current date range to offset 0"
    )
    def resume_with_inflight_part_reset(self, request, queryset):
        """Recover a paused job whose committed byte offset no longer matches the
        source bytes (re-download of a nondeterministic export, or a source file
        replaced after a data-error pause). Safe for sources with deterministic
        event UUIDs, which dedupe the re-imported overlap."""
        for batch_import in queryset:
            try:
                reset_key = batch_import.resume_with_inflight_part_reset()
            except ValueError as e:
                self.message_user(request, f"{batch_import.id}: {e}", level=messages.WARNING)
            else:
                self.message_user(
                    request,
                    f"{batch_import.id}: resumed; part {reset_key} will re-import from offset 0",
                    level=messages.SUCCESS,
                )

    @admin.display(description="Sink Type")
    def get_sink_type(self, obj):
        """Extract sink from import_config.sink"""
        if not obj.import_config:
            return None
        sink = obj.import_config.get("sink", {})
        return sink.get("type", "N/A")

    @admin.display(description="Send Rate")
    def get_send_rate(self, obj):
        """Extract send_rate from import_config.sink"""
        if not obj.import_config:
            return None
        sink = obj.import_config.get("sink", {})
        return sink.get("send_rate", "N/A")
