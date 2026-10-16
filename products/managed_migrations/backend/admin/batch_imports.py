from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from products.managed_migrations.backend.models.batch_imports import DEFAULT_SEND_RATE, BatchImport


class BatchImportAdminForm(forms.ModelForm):
    sink_type = forms.ChoiceField(
        choices=[("capture", "Capture"), ("kafka", "Kafka")],
        required=False,
        help_text="Capture sends events via HTTP; Kafka writes directly to Kafka.",
    )
    send_rate = forms.IntegerField(
        required=False,
        help_text=f"Events per second to send (e.g., {DEFAULT_SEND_RATE}). Leave empty to keep current value.",
        widget=forms.NumberInput(attrs={"placeholder": f"e.g., {DEFAULT_SEND_RATE}"}),
    )

    class Meta:
        model = BatchImport
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A worker can change the row between page load and save. Compare each submitted value
        # with the value the page showed, not with the row at save time, so that only the
        # operator's own edits count as changes.
        for field in self.fields.values():
            field.show_hidden_initial = True
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
                "send_rate": send_rate if send_rate is not None else existing_sink.get("send_rate", DEFAULT_SEND_RATE),
            }
            if sink_type == "kafka":
                sink["topic"] = existing_sink.get("topic", "historical")
                sink["transaction_timeout_seconds"] = existing_sink.get("transaction_timeout_seconds", 60)

            instance.import_config["sink"] = sink

        if commit:
            instance.save()
        return instance


EDITABLE_MODEL_FIELDS = ("team", "created_by_id", "status", "status_message")
SINK_FORM_FIELDS = ("sink_type", "send_rate")


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
        "pending_commit",
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
                    "pending_commit",
                ),
                "description": (
                    "A running job with a future leased_until is actively claimed by a worker. "
                    "Changing the status to running, or using a resume action, clears the lease, backoff "
                    "and pending commit so a worker can claim the job at once. A pending commit on "
                    "a job no worker holds means a worker stopped mid-commit: the chunk it names "
                    "may or may not have reached the sink. Choosing a resume action: 'Resume (keep progress)' "
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

    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
            return

        # A full-row save would also write the state, lease and backoff values loaded with the
        # form, which overwrites the progress a running worker saved since then.
        update_fields = [name for name in form.changed_data if name in EDITABLE_MODEL_FIELDS]
        if any(name in form.changed_data for name in SINK_FORM_FIELDS):
            update_fields.append("import_config")
        if "status" in form.changed_data and obj.status == BatchImport.Status.RUNNING:
            message = obj.status_message if "status_message" in form.changed_data else "Resumed by admin"
            update_fields.extend(obj.reset_for_resume(message))
        if update_fields:
            obj.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))

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

    @admin.action(
        description="Resume (keep progress) - continue paused import from its saved offset",
        permissions=["change"],
    )
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
        description="Resume + re-import in-flight part - reset paused import's current date range to offset 0",
        permissions=["change"],
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
