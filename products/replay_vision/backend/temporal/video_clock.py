"""Translation between the two clocks a scan deals with.

The rasterizer cuts inactive stretches out of the rendered MP4, so a position in the video runs
behind the wall-clock moment it shows. Everything the model sees is on the video clock, because that
is the clock it can index exactly; everything we persist is on the session clock, because that is
what the player seeks to.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from posthog.dataclasses import frozen


@frozen
class ActiveSpan:
    """One stretch the rasterizer kept, on both clocks."""

    session_from_s: float
    session_to_s: float
    video_from_s: float
    video_to_s: float


@frozen
class VideoClock:
    """Maps session seconds to video seconds and back, across the cuts the rasterizer made."""

    spans: tuple[ActiveSpan, ...]

    @property
    def is_identity(self) -> bool:
        return not self.spans

    @property
    def video_duration_s(self) -> float | None:
        """Length of the rendered video, which bounds any position the model can cite."""
        return self.spans[-1].video_to_s if self.spans else None

    def session_ms_to_video_s(self, session_ms: int) -> float:
        if self.is_identity:
            return session_ms / 1000
        session_s = session_ms / 1000
        for span in self.spans:
            if session_s < span.session_from_s:
                return span.video_from_s  # inside a cut: the video jumps straight to here
            if session_s <= span.session_to_s:
                return span.video_from_s + (session_s - span.session_from_s)
        return self.spans[-1].video_to_s

    def video_s_to_session_ms(self, video_s: float) -> int:
        if self.is_identity:
            return int(video_s * 1000)
        for span in self.spans:
            if video_s < span.video_from_s:
                return int(span.session_from_s * 1000)
            if video_s <= span.video_to_s:  # a boundary instant resolves to the stretch before the cut
                return int((span.session_from_s + (video_s - span.video_from_s)) * 1000)
        return int(self.spans[-1].session_to_s * 1000)


def _spans_from_periods(periods: Iterable[dict[str, Any]]) -> list[ActiveSpan]:
    # `ts_*` is the session clock and `recording_ts_*` the video clock, despite how the names read.
    spans = [
        ActiveSpan(
            session_from_s=float(p["ts_from_s"]),
            session_to_s=float(p["ts_to_s"]),
            video_from_s=float(p["recording_ts_from_s"]),
            video_to_s=float(p["recording_ts_to_s"]),
        )
        for p in periods
        if p.get("active")
    ]
    spans.sort(key=lambda span: span.video_from_s)
    return spans


def video_clock_from_export_context(export_context: dict[str, Any] | None) -> VideoClock:
    """Build the clock from a rendered asset's context. Falls back to identity, which is correct only
    when nothing was cut — callers should log when periods are missing from an asset that has them."""
    periods: Sequence[dict[str, Any]] = (export_context or {}).get("inactivity_periods") or []
    if not periods:
        return VideoClock(spans=())
    return VideoClock(spans=tuple(_spans_from_periods(periods)))
