from enum import Enum
from typing import Self

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDTModel


class DateRangeExportSource(str, Enum):
    MIXPANEL = "mixpanel"
    AMPLITUDE = "amplitude"


class ContentType(str, Enum):
    MIXPANEL = "mixpanel"
    CAPTURED = "captured"
    AMPLITUDE = "amplitude"

    def serialize(self) -> dict:
        return {"type": self.value}


class BatchImport(ModelActivityMixin, UUIDTModel):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        PAUSED = "paused", "Paused"
        RUNNING = "running", "Running"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    lease_id = models.TextField(null=True, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)
    status = models.TextField(choices=Status, default=Status.RUNNING)
    # Status message to save to the job, so that a developer can debug why a commit might have failed
    # Not displayed to the user
    status_message = models.TextField(null=True, blank=True)
    # Status message to be displayed to the user
    display_status_message = models.TextField(null=True, blank=True)
    state = models.JSONField(null=True, blank=True)
    import_config = models.JSONField()
    secrets = EncryptedJSONStringField()
    # Exponential backoff state (used by rust worker). Mirrors columns used by the worker.
    backoff_attempt = models.IntegerField(default=0)
    backoff_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_batchimport"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._config_builder = BatchImportConfigBuilder(self, initialize_empty=not self.import_config)

    @property
    def config(self) -> "BatchImportConfigBuilder":
        return self._config_builder

    def parts_progress(self) -> tuple[int, int, dict | None]:
        """Summarize worker part state: (done_count, total_count, first_unfinished_part).

        Mirrors the worker's `PartState::is_done`: a part is done when it has a known
        `total_size` that `current_offset` has reached. The worker processes parts in
        order, so the first unfinished part is the one in flight (or next up).
        """
        parts = (self.state or {}).get("parts") or []
        # Defensive .get throughout: this renders on every admin changelist row, so
        # one partially shaped worker-owned part dict must not 500 the whole list.
        done = sum(
            1 for p in parts if p.get("total_size") is not None and p.get("current_offset", 0) >= p["total_size"]
        )
        inflight = next(
            (p for p in parts if p.get("total_size") is None or p.get("current_offset", 0) < p["total_size"]),
            None,
        )
        return done, len(parts), inflight

    def resume_after_pause(self) -> None:
        """Resume a paused import from its saved progress.

        Flips the job to running and clears the worker lease and backoff - pausing
        keeps the worker's lease, so without clearing it no worker can re-claim the
        row for up to 30 minutes. Part offsets are untouched: use this when the
        source bytes behind the saved offset are unchanged (transient pauses, or a
        data fix that preserved byte offsets). When the bytes changed underneath the
        offset, use `resume_with_inflight_part_reset` instead. Raises ValueError if
        the job is not paused.
        """
        if self.status != BatchImport.Status.PAUSED:
            raise ValueError(f"Only paused imports can be resumed (status: {self.status})")
        self._flip_to_running("Resumed by admin")

    def resume_with_inflight_part_reset(self) -> str:
        """Resume a paused import whose in-flight part has a poisoned byte offset.

        A part's committed offset is only meaningful against the exact byte stream it
        was measured on. When the worker re-downloads a part (pod replacement without
        temp-bucket staging, or a source file replaced after a data-error pause), the
        saved offset can land mid-record in the new stream and the job pauses with a
        parse error at the resume point. The fix is to re-import that part from
        offset 0 - safe for sources with deterministic event UUIDs (Mixpanel
        $insert_id, Amplitude uuid), which dedupe the overlap.

        Resets the first unfinished part to offset 0, then resumes as
        `resume_after_pause` does. Returns the key of the reset part. Raises
        ValueError if the job is not paused or has no unfinished part.
        """
        if self.status != BatchImport.Status.PAUSED:
            raise ValueError(f"Only paused imports can be reset and resumed (status: {self.status})")

        _done, _total, inflight = self.parts_progress()
        if inflight is None:
            raise ValueError("No unfinished part to reset - the job has no resumable work")

        inflight["current_offset"] = 0
        # A stale total from a previous download would be wrong too: each download of
        # a nondeterministic export can have a different decompressed size.
        inflight["total_size"] = None

        self._flip_to_running(f"Resumed by admin with part {inflight['key']} reset to offset 0")
        return inflight["key"]

    def _flip_to_running(self, status_message: str) -> None:
        self.status = BatchImport.Status.RUNNING
        self.status_message = status_message
        self.display_status_message = None
        self.lease_id = None
        self.leased_until = None
        self.backoff_attempt = 0
        self.backoff_until = None
        self.save(
            update_fields=[
                "state",
                "status",
                "status_message",
                "display_status_message",
                "lease_id",
                "leased_until",
                "backoff_attempt",
                "backoff_until",
                "updated_at",
            ]
        )


# Mostly used for manual job creation
class BatchImportConfigBuilder:
    def __init__(self, batch_import: BatchImport, initialize_empty: bool = True):
        self.batch_import = batch_import
        if initialize_empty:
            self.batch_import.import_config = {}
            self.batch_import.secrets = {}

    def json_lines(self, content_type: ContentType, skip_blanks: bool = True) -> Self:
        self.batch_import.import_config["data_format"] = {
            "type": "json_lines",
            "skip_blanks": skip_blanks,
            "content": content_type.serialize(),
        }
        return self

    def from_folder(self, path: str) -> Self:
        self.batch_import.import_config["source"] = {"type": "folder", "path": path}
        return self

    def from_urls(
        self, urls: list[str], urls_key: str = "urls", allow_internal_ips: bool = False, timeout_seconds: int = 30
    ) -> Self:
        self.batch_import.import_config["source"] = {
            "type": "url_list",
            "urls_key": urls_key,
            "allow_internal_ips": allow_internal_ips,
            "timeout_seconds": timeout_seconds,
        }
        self.batch_import.secrets[urls_key] = urls
        return self

    def from_s3(
        self,
        bucket: str,
        prefix: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str | None = None,
        access_key_id_key: str = "aws_access_key_id",
        secret_access_key_key: str = "aws_secret_access_key",
    ) -> Self:
        source: dict = {
            "type": "s3",
            "bucket": bucket,
            "prefix": prefix,
            "region": region,
            "access_key_id_key": access_key_id_key,
            "secret_access_key_key": secret_access_key_key,
        }
        if endpoint_url:
            source["endpoint_url"] = endpoint_url
        self.batch_import.import_config["source"] = source
        self.batch_import.secrets[access_key_id_key] = access_key_id
        self.batch_import.secrets[secret_access_key_key] = secret_access_key
        return self

    def from_s3_gzip(
        self,
        bucket: str,
        prefix: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str | None = None,
        access_key_id_key: str = "aws_access_key_id",
        secret_access_key_key: str = "aws_secret_access_key",
    ) -> Self:
        source: dict = {
            "type": "s3_gzip",
            "bucket": bucket,
            "prefix": prefix,
            "region": region,
            "access_key_id_key": access_key_id_key,
            "secret_access_key_key": secret_access_key_key,
        }
        if endpoint_url:
            source["endpoint_url"] = endpoint_url
        self.batch_import.import_config["source"] = source
        self.batch_import.secrets[access_key_id_key] = access_key_id
        self.batch_import.secrets[secret_access_key_key] = secret_access_key
        return self

    def from_date_range(
        self,
        start_date: str,
        end_date: str,
        access_key: str,
        secret_key: str,
        export_source: DateRangeExportSource,
        access_key_key: str = "api_key",
        secret_key_key: str = "secret_key",
        is_eu_region: bool = False,
    ) -> Self:
        # there is a bunch of annoying business logic around how each endpoint behaves (what requests an endpoint expects, what it responds with, etc.)
        # jam a bunch of that messy configuration here to keep it off the batch-import-worker and out of the client
        match export_source:
            case DateRangeExportSource.AMPLITUDE:
                if is_eu_region:
                    base_url = "https://analytics.eu.amplitude.com/api/2/export"
                else:
                    base_url = "https://amplitude.com/api/2/export"
                auth_config = {
                    "type": "basic_auth",
                    "username_secret": access_key_key,
                    "password_secret": secret_key_key,
                }
                additional_config = {
                    "extractor_type": "zip_gzip_json",
                    "is_compressed": True,
                    "start_qp": "start",
                    "end_qp": "end",
                    "date_format": "%Y%m%dT%H",
                    # The smallest duration we can request from amplitude is 1 hour at a time
                    "interval_duration": 3600,
                    # Amplitude exports can be large and slow for high-volume hours;
                    # 10 minutes gives enough headroom for big exports without masking real failures.
                    "timeout_seconds": 600,
                }
            case DateRangeExportSource.MIXPANEL:
                if is_eu_region:
                    base_url = "https://data-eu.mixpanel.com/api/2.0/export"
                else:
                    base_url = "https://data.mixpanel.com/api/2.0/export"
                auth_config = {
                    "type": "mixpanel_auth",
                    "secret_key_secret": secret_key_key,
                }
                additional_config = {
                    "extractor_type": "plain_gzip",
                    "is_compressed": True,
                    "start_qp": "from_date",
                    "end_qp": "to_date",
                    "date_format": "%Y-%m-%d",
                    # Smallest duration that we can request form mixpanel is 1 day at a time :(
                    # folks with bigger exports will almost certainly need to use s3/static storage source instead
                    # as we can't reasonably download a day's worth of big customer's data to our workers at a time
                    "interval_duration": 86400,
                    # Mixpanel endpoint is slow and can only request a day at a time at minimum so we need a long timeout
                    "timeout_seconds": 300,
                    "headers": {"Accept-Encoding": "gzip"},
                }
            case _:
                raise ValueError(f"Unsupported export source: {export_source}")

        self.batch_import.import_config["source"] = {
            "type": "date_range_export",
            "start": start_date,
            "end": end_date,
            "auth": auth_config,
            "base_url": base_url,
            **additional_config,
        }
        self.batch_import.secrets[access_key_key] = access_key
        self.batch_import.secrets[secret_key_key] = secret_key
        return self

    def to_stdout(self, as_json: bool = True) -> Self:
        self.batch_import.import_config["sink"] = {"type": "stdout", "as_json": as_json}
        return self

    def to_file(self, path: str, as_json: bool = True, cleanup: bool = False) -> Self:
        self.batch_import.import_config["sink"] = {"type": "file", "path": path, "as_json": as_json, "cleanup": cleanup}
        return self

    def to_kafka(self, topic: str, send_rate: int, transaction_timeout_seconds: int) -> Self:
        self.batch_import.import_config["sink"] = {
            "type": "kafka",
            "topic": topic,
            "send_rate": send_rate,
            "transaction_timeout_seconds": transaction_timeout_seconds,
        }
        return self

    def to_capture(self, send_rate: int) -> Self:
        self.batch_import.import_config["sink"] = {
            "type": "capture",
            "send_rate": send_rate,
        }
        return self

    def to_noop(self) -> Self:
        self.batch_import.import_config["sink"] = {"type": "noop"}
        return self

    def with_import_events(self, import_events: bool = True) -> Self:
        """Set whether to import events from the source"""
        self.batch_import.import_config["import_events"] = import_events
        return self

    def with_generate_identify_events(self, generate_identify_events: bool = True) -> Self:
        """Set whether to generate identify events for linking user IDs with device IDs (Amplitude specific)"""
        self.batch_import.import_config["generate_identify_events"] = generate_identify_events
        return self

    def with_generate_group_identify_events(self, generate_group_identify_events: bool = True) -> Self:
        """Set whether to generate group identify events from group property changes (Amplitude specific)"""
        self.batch_import.import_config["generate_group_identify_events"] = generate_group_identify_events
        return self
