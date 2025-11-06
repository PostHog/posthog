import hashlib
import dataclasses
from datetime import datetime
from typing import Any, cast

from products.enterprise.backend.hogai.session_summaries.utils import (
    generate_full_event_id,
    get_column_index,
    prepare_datetime,
)


@dataclasses.dataclass(frozen=True)
class SessionSummaryMetadata:
    start_time: datetime | None = None
    duration: int | None = None
    console_error_count: int | None = None
    active_seconds: int | None = None
    click_count: int | None = None
    keypress_count: int | None = None
    mouse_activity_count: int | None = None
    start_url: str | None = None

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        if self.start_time:
            d["start_time"] = self.start_time.isoformat()
        return d


@dataclasses.dataclass
class SessionSummaryPromptData:
    # We may allow customisation of columns included in the future, and we alter the columns present
    # as we process the data, so want to stay as loose as possible here
    columns: list[str] = dataclasses.field(default_factory=list)
    results: list[list[Any]] = dataclasses.field(default_factory=list)
    metadata: SessionSummaryMetadata = dataclasses.field(default_factory=SessionSummaryMetadata)
    # In order to reduce the number of tokens in the prompt,
    # we generate mappings to use in the prompt instead of repeating the data
    window_id_mapping: dict[str, str] = dataclasses.field(default_factory=dict)
    url_mapping: dict[str, str] = dataclasses.field(default_factory=dict)

    def load_session_data(
        self,
        raw_session_events: list[tuple[str | datetime | list[str] | None, ...]],
        raw_session_metadata: dict[str, Any],
        raw_session_columns: list[str],
        session_id: str,
    ) -> tuple[dict[str, list[str | int | list[str] | None]], dict[str, str]]:
        """
        Create session summary prompt data from session data, and return a mapping of event ids to events
        to combine events data with the LLM output (avoid LLM returning/hallucinating the event data in the output).
        """
        if not raw_session_events:
            raise ValueError(f"No session events provided for summarizing session_id {session_id}")
        if not raw_session_metadata:
            raise ValueError(f"No session metadata provided for summarizing session_id {session_id}")
        self.columns = ["event_id", "event_index", *raw_session_columns]
        self.metadata = self._prepare_metadata(raw_session_metadata)
        simplified_events_mapping: dict[str, list[Any]] = {}
        event_ids_mapping: dict[str, str] = {}
        # Pick indexes as we iterate over arrays
        event_id_index, event_index_index = 0, 1
        window_id_index = get_column_index(self.columns, "$window_id")
        current_url_index = get_column_index(self.columns, "$current_url")
        timestamp_index = get_column_index(self.columns, "timestamp")
        # Iterate session events once to decrease the number of tokens in the prompt through mappings
        for i, event in enumerate(raw_session_events):
            # Copy the event to avoid mutating the original, add new columns for event_id and event_index
            event_uuid = cast(str, event[-1])  # UUID should come last as we use it to generate event_id, but not after
            simplified_event: list[str | datetime | list[str] | int | None] = [None, None, *list(event[:-1])]
            # Stringify timestamp to avoid datetime objects in the prompt
            if timestamp_index is not None:
                event_timestamp = simplified_event[timestamp_index]
                if not isinstance(event_timestamp, datetime):
                    raise ValueError(f"Timestamp is not a datetime: {event_timestamp}")
                # All timestamps are stringified, so no datetime in the output type
                simplified_event[timestamp_index] = event_timestamp.isoformat()
            # Simplify Window IDs
            if window_id_index is not None:
                event_window_id = simplified_event[window_id_index]
                if event_window_id is None:
                    # Non-browser events (like Python SDK ones) could have no window ID
                    simplified_event[window_id_index] = None
                elif not isinstance(event_window_id, str):
                    raise ValueError(f"Window ID is not a string: {event_window_id}")
                else:
                    simplified_event[window_id_index] = self._simplify_window_id(event_window_id)
            # Simplify URLs
            if current_url_index is not None:
                event_current_url = simplified_event[current_url_index]
                if event_current_url is None:
                    # Non-browser events (like Python SDK ones) could have no URL
                    simplified_event[current_url_index] = None
                elif not isinstance(event_current_url, str):
                    raise ValueError(f"Current URL is not a string: {event_current_url}")
                else:
                    simplified_event[current_url_index] = self._simplify_url(event_current_url)
            # Generate full event ID from session and event UUIDs to be able to track them across sessions
            full_event_id = generate_full_event_id(session_id=session_id, event_uuid=event_uuid)
            # Generate a hex for each event to make sure we can identify repeated events, and identify the event
            event_id = self._get_deterministic_hex(simplified_event)
            if event_id in simplified_events_mapping:
                # Skip repeated events
                continue
            simplified_event[event_id_index] = event_id
            simplified_event[event_index_index] = i
            simplified_events_mapping[event_id] = simplified_event
            # Store full event ID into the mapping to avoid providing full IDs to LLM (6 tokens vs 52 tokens per event)
            event_ids_mapping[event_id] = full_event_id
        self.results = list(simplified_events_mapping.values())
        return simplified_events_mapping, event_ids_mapping

    @staticmethod
    def _prepare_metadata(raw_session_metadata: dict[str, Any]) -> SessionSummaryMetadata:
        # Remove excessive data or fields that negatively impact the LLM performance
        # For example, listing 114 errors, increases chances of error hallucination
        session_metadata = raw_session_metadata.copy()  # Avoid mutating the original
        allowed_fields = (
            "start_time",
            "duration",
            "recording_duration",
            "console_error_count",
            "active_seconds",
            "click_count",
            "keypress_count",
            "mouse_activity_count",
            "start_url",
        )
        session_metadata = {k: v for k, v in session_metadata.items() if k in allowed_fields}
        # Start time, duration and console error count should be always present
        if "start_time" not in session_metadata:
            raise ValueError(f"start_time is required in session metadata: {session_metadata}")
        if "console_error_count" not in session_metadata:
            raise ValueError(f"console_error_count is required in session metadata: {session_metadata}")
        start_time = prepare_datetime(session_metadata["start_time"])
        console_error_count = session_metadata["console_error_count"]
        duration = session_metadata.get("duration") or session_metadata.get("recording_duration")
        if duration is None:
            raise ValueError(f"duration/recording_duration is required in session metadata: {session_metadata}")
        return SessionSummaryMetadata(
            start_time=start_time,
            duration=duration,
            console_error_count=console_error_count,
            active_seconds=session_metadata.get("active_seconds"),
            click_count=session_metadata.get("click_count"),
            keypress_count=session_metadata.get("keypress_count"),
            mouse_activity_count=session_metadata.get("mouse_activity_count"),
            start_url=session_metadata.get("start_url"),
        )

    def _simplify_window_id(self, window_id: str | None) -> str | None:
        if not window_id:
            return None
        if window_id not in self.window_id_mapping:
            self.window_id_mapping[window_id] = f"window_{len(self.window_id_mapping) + 1}"
        return self.window_id_mapping[window_id]

    def _simplify_url(self, url: str | None) -> str | None:
        if not url:
            return None
        if url not in self.url_mapping:
            self.url_mapping[url] = f"url_{len(self.url_mapping) + 1}"
        return self.url_mapping[url]

    @staticmethod
    def _get_deterministic_hex(event: list[Any], length: int = 8) -> str:
        """
        Generate a hex for each event to make sure we can identify repeated events.
        """

        def format_value(val: Any) -> str:
            if isinstance(val, datetime):
                return val.isoformat()
            return str(val)

        # Join with a null byte as delimiter since it won't appear in normal strings,
        # so we can get the same string using the same combination of values only.
        event_string = "\0".join(format_value(x) for x in event)
        return hashlib.sha256(event_string.encode()).hexdigest()[:length]
