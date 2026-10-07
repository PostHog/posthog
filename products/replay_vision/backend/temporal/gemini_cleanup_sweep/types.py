from datetime import datetime

from pydantic import BaseModel


class CleanupSweepInputs(BaseModel, frozen=True):
    pass


class CleanupSweepResult(BaseModel, frozen=True):
    scanned: int = 0
    deleted: int = 0
    skipped_running: int = 0
    skipped_too_young: int = 0
    skipped_temporal_error: int = 0
    skipped_invalid_value: int = 0
    delete_failed: int = 0
    hit_max_files_cap: bool = False
    storage_files: int | None = None
    storage_bytes: int | None = None
    storage_listing_truncated: bool = False


class TrackedFile(BaseModel, frozen=True):
    gemini_file_name: str
    workflow_id: str
    uploaded_at: datetime


class GeminiStorageUsage(BaseModel, frozen=True):
    files: int
    total_bytes: int
    oldest_created_at: datetime | None
    truncated: bool
