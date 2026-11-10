"""Translation between the two clocks a scan deals with.

The rasterizer cuts inactive stretches out of the rendered MP4, so a position in the video runs
behind the wall-clock moment it shows. Everything the model sees is on the video clock, because that
is the clock it can index exactly; everything we persist is on the session clock, because that is
what the player seeks to.

A cut costs the frame the render spent performing it, so kept stretches are not contiguous on the video
clock. `clipTimeForMoment` in products/desktop/packages/ui/src/features/inbox/components/detail/recordingClipTime.ts
is the TypeScript sibling of this mapping. The two have to change together.
"""

from dataclasses import replace
from typing import Any

from posthog.dataclasses import frozen
from posthog.temporal.session_replay.rasterize_recording.types import InactivityPeriod


@frozen
class ActiveSpan:
    """One stretch the rasterizer kept, on both clocks."""

    session_from_s: float
    session_to_s: float
    video_from_s: float
    video_to_s: float


@frozen
class IdleStretch:
    """One stretch the player marked inactive, in session milliseconds."""

    start_ms: int
    end_ms: int


@frozen
class VideoClock:
    """Maps session seconds to video seconds and back, across the cuts the rasterizer made.

    No spans means the render cut nothing, so both clocks read the same.
    """

    spans: tuple[ActiveSpan, ...]
    # The stretches the player marked inactive, as (from, to) session seconds. The render cut them from the video.
    inactive: tuple[tuple[float, float], ...] = ()

    @property
    def is_identity(self) -> bool:
        return not self.spans

    @property
    def video_duration_s(self) -> float | None:
        """Length of the rendered video, which bounds any position the model can cite."""
        return self.spans[-1].video_to_s if self.spans else None

    def citable_duration_s(self, session_duration_s: float | None) -> float | None:
        """The last second the model can cite: the video's length, or the session's when nothing was cut."""
        return session_duration_s if self.is_identity else self.video_duration_s

    def session_ms_to_video_s(self, session_ms: int) -> float:
        return self._project(session_ms / 1000, to_video=True)

    def video_s_to_session_ms(self, video_s: float) -> int:
        return int(self._project(video_s, to_video=False) * 1000)

    def video_end_s_to_session_ms(self, video_s: float) -> int:
        """Where a range that ends at `video_s` ends on the session clock.

        A second shared across a cut resolves to the earlier stretch here, so a range that stops at a cut ends
        where the user went idle rather than where they came back.
        """
        if self.is_identity:
            return int(video_s * 1000)
        for index, span in enumerate(self.spans):
            if video_s <= span.video_to_s:
                # A range ending at a cut, or in the frame the cut costs, ends with the stretch before the cut.
                if video_s <= span.video_from_s and index > 0:
                    return int(self.spans[index - 1].session_to_s * 1000)
                return int((span.session_from_s + max(0.0, video_s - span.video_from_s)) * 1000)
        return int(self.spans[-1].session_to_s * 1000)

    def cuts_video_s(self) -> list[float]:
        """The video seconds where the render cut inactive time, so the video jumps forward on the session clock."""
        return [
            later.video_from_s
            for earlier, later in zip(self.spans, self.spans[1:])
            if later.session_from_s > earlier.session_to_s
        ]

    def inactive_session_ms(self, duration_ms: int) -> list[IdleStretch]:
        """The inactive stretches, clipped to the session, in order and merged where they touch."""
        merged: list[IdleStretch] = []
        for from_s, to_s in sorted(self.inactive):
            stretch = IdleStretch(start_ms=max(0, int(from_s * 1000)), end_ms=min(duration_ms, int(to_s * 1000)))
            if stretch.end_ms <= stretch.start_ms:
                continue
            if merged and stretch.start_ms <= merged[-1].end_ms:
                merged[-1] = replace(merged[-1], end_ms=max(merged[-1].end_ms, stretch.end_ms))
            else:
                merged.append(stretch)
        return merged

    def video_s_to_session_s(self, video_s: float) -> int:
        return int(self._project(video_s, to_video=False))

    def _project(self, value_s: float, *, to_video: bool) -> float:
        """Walk the kept stretches and move `value_s` onto the other clock.

        A value inside a cut has only one place it could be shown, so it collapses onto the point the
        video resumes; past the end clamps.

        A cut takes no time on the video clock, so the stretch after it can begin on the very second the
        stretch before it ends. Such a second resolves to the later stretch, because that is the content the
        video shows there, and choosing the earlier one would seek back by the whole length of the cut.
        """
        if self.is_identity:
            return value_s
        for index, span in enumerate(self.spans):
            src_from, src_to = (
                (span.session_from_s, span.session_to_s) if to_video else (span.video_from_s, span.video_to_s)
            )
            dst_from = span.video_from_s if to_video else span.session_from_s
            if value_s < src_from:
                return dst_from
            if value_s <= src_to:
                shares_boundary = (
                    not to_video
                    and value_s == src_to
                    and index + 1 < len(self.spans)
                    and self.spans[index + 1].video_from_s == value_s
                )
                if shares_boundary:
                    continue
                return dst_from + (value_s - src_from)
        last = self.spans[-1]
        return last.video_to_s if to_video else last.session_to_s


def video_clock_from_export_context(export_context: dict[str, Any] | None) -> VideoClock | None:
    """The clock a rendered asset describes, or None when the asset never recorded what it cut.

    A completed render always writes the map, so a present-but-empty one is proof that nothing was
    cut. Only an asset rendered before the rasterizer recorded it at all is genuinely unknown.
    """
    if export_context is None or "inactivity_periods" not in export_context:
        return None
    periods = [InactivityPeriod.model_validate(p) for p in export_context["inactivity_periods"] or []]
    spans = [
        ActiveSpan(
            session_from_s=p.ts_from_s,
            session_to_s=p.ts_to_s,
            video_from_s=p.recording_ts_from_s,
            video_to_s=p.recording_ts_to_s,
        )
        for p in periods
        # A period missing either clock cannot be mapped; dropping it leaves the surrounding spans intact.
        if p.active and p.ts_to_s is not None and p.recording_ts_from_s is not None and p.recording_ts_to_s is not None
    ]
    spans.sort(key=lambda span: span.video_from_s)
    inactive = tuple((p.ts_from_s, p.ts_to_s) for p in periods if not p.active and p.ts_to_s is not None)
    return VideoClock(spans=tuple(spans), inactive=inactive)
