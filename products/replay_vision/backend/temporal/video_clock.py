"""Translation between the two clocks a scan deals with.

The rasterizer cuts inactive stretches out of the rendered MP4, so a position in the video runs
behind the wall-clock moment it shows. Everything the model sees is on the video clock, because that
is the clock it can index exactly; everything we persist is on the session clock, because that is
what the player seeks to.

A cut costs the frame the render spent performing it, so kept stretches are not contiguous on the video
clock. `clipTimeForMoment` in products/desktop/packages/ui/src/features/inbox/components/detail/recordingClipTime.ts
is the TypeScript sibling of this mapping. The two have to change together.
"""

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
class VideoClock:
    """Maps session seconds to video seconds and back, across the cuts the rasterizer made.

    No spans means the render cut nothing, so both clocks read the same.
    """

    spans: tuple[ActiveSpan, ...]

    @property
    def is_identity(self) -> bool:
        return not self.spans

    @property
    def video_duration_s(self) -> float | None:
        """Length of the rendered video, which bounds any position the model can cite."""
        return self.spans[-1].video_to_s if self.spans else None

    def session_ms_to_video_s(self, session_ms: int) -> float:
        return self._project(session_ms / 1000, to_video=True)

    def video_s_to_session_ms(self, video_s: float) -> int:
        return int(self._project(video_s, to_video=False) * 1000)

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
    return VideoClock(spans=tuple(spans))
