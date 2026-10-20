from uuid import NAMESPACE_URL, uuid5

from posthog.dataclasses import frozen

PROCESS_KILLED_METHOD = "_posthog/process_killed"
PROCESS_KILLED_EVENT = "sandbox_process_killed"
_BYTES_PER_GIB = 1024**3


@frozen
class ProcessKilledNotice:
    comm: str
    signal: str
    tree_rss_bytes: int
    memory_current_bytes: int
    memory_limit_bytes: int

    def analytics_properties(self) -> dict[str, str | int]:
        return {
            "process_comm": self.comm,
            "process_signal": self.signal,
            "process_tree_rss_bytes": self.tree_rss_bytes,
            "memory_current_bytes": self.memory_current_bytes,
            "memory_limit_bytes": self.memory_limit_bytes,
        }


def _byte_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def parse_process_killed(event_data: dict) -> ProcessKilledNotice | None:
    if event_data.get("type") != "notification":
        return None
    notification = event_data.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != PROCESS_KILLED_METHOD:
        return None
    params = notification.get("params")
    if not isinstance(params, dict):
        return None
    comm = params.get("comm")
    signal = params.get("signal")
    tree_rss_bytes = _byte_count(params.get("treeRssBytes"))
    memory_current_bytes = _byte_count(params.get("memoryCurrentBytes"))
    memory_limit_bytes = _byte_count(params.get("memoryLimitBytes"))
    if not isinstance(comm, str) or not isinstance(signal, str):
        return None
    if tree_rss_bytes is None or memory_current_bytes is None or memory_limit_bytes is None:
        return None
    return ProcessKilledNotice(
        comm=comm,
        signal=signal,
        tree_rss_bytes=tree_rss_bytes,
        memory_current_bytes=memory_current_bytes,
        memory_limit_bytes=memory_limit_bytes,
    )


def process_killed_event_uuid(run_id: str, sequence: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"posthog-task-process-killed:{run_id}:{sequence}"))


def _format_gib(size_bytes: int) -> str:
    return f"{size_bytes / _BYTES_PER_GIB:.1f} GiB"


def format_process_killed_message(notice: ProcessKilledNotice) -> str:
    return (
        f"The sandbox stopped {notice.comm} because it was using {_format_gib(notice.tree_rss_bytes)} "
        f"of the {_format_gib(notice.memory_limit_bytes)} available. The agent is still running."
    )
