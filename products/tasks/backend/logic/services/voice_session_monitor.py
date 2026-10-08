from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from posthog.dataclasses import frozen

CLOSE_GRACE = timedelta(seconds=30)
HEARTBEAT_INTERVAL_SECONDS = 10.0

VoiceCloseReason = Literal["provider", "close_timeout", "disconnected", "unavailable", "monitor_failed"]


class LiveSessionDisconnected(Exception):
    pass


class LiveSessionConnection(Protocol):
    async def send(self, event: dict[str, Any]) -> None: ...

    async def receive(self, timeout: float) -> dict[str, Any] | None:
        """The next provider event, or None when the timeout passes first. Raises LiveSessionDisconnected."""
        ...


@frozen
class DelegatedResponseUsage:
    response_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int


@frozen
class VoiceSessionOutcome:
    seconds: int | None
    reason: VoiceCloseReason
    provider_reason: str | None
    confirmed: bool
    limit_reached: bool


@frozen(frozen=False)
class VoiceSessionProgress:
    seconds: int | None = None
    close_requested_at: datetime | None = None
    limit_reached: bool = False

    def outcome(self, reason: VoiceCloseReason, *, confirmed: bool = False) -> VoiceSessionOutcome:
        return VoiceSessionOutcome(
            seconds=self.seconds,
            reason=reason,
            provider_reason=None,
            confirmed=confirmed,
            limit_reached=self.limit_reached,
        )


async def monitor_live_session(
    connection: LiveSessionConnection,
    progress: VoiceSessionProgress,
    *,
    deadline: datetime,
    now: Callable[[], datetime],
    heartbeat: Callable[[int | None], None],
    on_response_usage: Callable[[DelegatedResponseUsage], None],
) -> VoiceSessionOutcome:
    """Follow a live session until it closes, and close it at the deadline."""
    while True:
        current = now()
        if progress.close_requested_at is None and current >= deadline:
            progress.close_requested_at = current
            progress.limit_reached = True
            await connection.send({"type": "session.close"})
        wait_until = deadline if progress.close_requested_at is None else progress.close_requested_at + CLOSE_GRACE
        if progress.close_requested_at is not None and current >= wait_until:
            return progress.outcome("close_timeout")
        heartbeat(progress.seconds)
        try:
            event = await connection.receive(min(HEARTBEAT_INTERVAL_SECONDS, (wait_until - current).total_seconds()))
        except LiveSessionDisconnected:
            if progress.close_requested_at is None:
                raise
            return progress.outcome("disconnected")
        if event is None:
            continue
        event_type = event.get("type")
        if event_type == "session.usage.updated":
            progress.seconds = _usage_seconds(event, progress.seconds)
        elif event_type == "response.event":
            usage = _delegated_response_usage(event.get("event"))
            if usage is not None:
                on_response_usage(usage)
        elif event_type == "session.closed":
            progress.seconds = _usage_seconds(event, progress.seconds)
            reason = event.get("reason")
            return VoiceSessionOutcome(
                seconds=progress.seconds,
                reason="provider",
                provider_reason=reason[:64] if isinstance(reason, str) else None,
                confirmed=True,
                limit_reached=progress.limit_reached,
            )


def _usage_seconds(event: dict[str, Any], fallback: int | None) -> int | None:
    usage = event.get("usage")
    seconds = usage.get("seconds") if isinstance(usage, dict) else None
    # Each snapshot replaces the previous total, so a later event never adds to it.
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds >= 0:
        return seconds
    return fallback


def _delegated_response_usage(event: object) -> DelegatedResponseUsage | None:
    if not isinstance(event, dict) or event.get("type") != "response.completed":
        return None
    response = event.get("response")
    if not isinstance(response, dict):
        return None
    response_id, model, usage = response.get("id"), response.get("model"), response.get("usage")
    if not isinstance(response_id, str) or not 0 < len(response_id) <= 128 or not isinstance(usage, dict):
        return None
    details = usage.get("input_tokens_details")
    return DelegatedResponseUsage(
        response_id=response_id,
        model=model[:128] if isinstance(model, str) else "unknown",
        input_tokens=_token_count(usage.get("input_tokens")),
        output_tokens=_token_count(usage.get("output_tokens")),
        cached_input_tokens=_token_count(details.get("cached_tokens") if isinstance(details, dict) else None),
    )


def _token_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
