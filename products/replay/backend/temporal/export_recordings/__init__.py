from collections.abc import Callable

from products.replay.backend.temporal.export_recordings.activities import export_shard, write_summary
from products.replay.backend.temporal.export_recordings.workflow import ExportRecordingsWorkflow

EXPORT_RECORDINGS_WORKFLOWS = [ExportRecordingsWorkflow]

EXPORT_RECORDINGS_ACTIVITIES: list[Callable[..., object]] = [export_shard, write_summary]
