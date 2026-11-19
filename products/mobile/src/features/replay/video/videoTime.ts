import type { ReplayVideoExportContext } from '@/api/replayVideo'
import { isRecord } from '@/lib/records'

// `video_clock.py` in `products/replay_vision/backend/temporal/` and `recordingClipTime.ts` in the desktop app map the
// same periods. The render cuts idle stretches out of the video, so the video runs behind the session clock.

interface MappedPeriod {
    active: boolean
    sessionFrom: number
    sessionTo: number | null
    videoFrom: number
    videoTo: number | null
}

function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value)
}

/** The periods that carry both clocks, in session order. A period without its video position cannot be placed. */
function mappedPeriods(periods: unknown): MappedPeriod[] {
    if (!Array.isArray(periods)) {
        return []
    }
    return periods
        .flatMap((period): MappedPeriod[] => {
            if (!isRecord(period) || !isFiniteNumber(period.ts_from_s) || !isFiniteNumber(period.recording_ts_from_s)) {
                return []
            }
            return [
                {
                    active: period.active !== false,
                    sessionFrom: period.ts_from_s,
                    sessionTo: isFiniteNumber(period.ts_to_s) ? Math.max(period.ts_to_s, period.ts_from_s) : null,
                    videoFrom: period.recording_ts_from_s,
                    videoTo: isFiniteNumber(period.recording_ts_to_s)
                        ? Math.max(period.recording_ts_to_s, period.recording_ts_from_s)
                        : null,
                },
            ]
        })
        .sort((a, b) => a.sessionFrom - b.sessionFrom)
}

/** A moment inside `period`. A skipped stretch has no length on the video clock, so it lands where playback resumed. */
function videoSecondsInside(period: MappedPeriod, sessionSeconds: number): number {
    const { sessionFrom, sessionTo, videoFrom, videoTo } = period
    if (sessionTo !== null && videoTo !== null) {
        const sessionSpan = sessionTo - sessionFrom
        if (sessionSpan <= 0) {
            return videoFrom
        }
        return videoFrom + ((sessionSeconds - sessionFrom) * (videoTo - videoFrom)) / sessionSpan
    }
    if (!period.active) {
        return videoFrom
    }
    const realTime = videoFrom + (sessionSeconds - sessionFrom)
    return videoTo === null ? realTime : Math.min(realTime, videoTo)
}

/**
 * The second of the rendered video that shows `sessionSeconds` into the recording. A moment before the first period or
 * between two periods lands where the next one starts, and one after the last period lands at its end. Without
 * periods the render cut nothing, so both clocks read the same. Never negative and never past the video's length.
 */
export function videoSecondsForSessionSeconds(
    sessionSeconds: number,
    context: ReplayVideoExportContext | undefined
): number {
    const videoDuration =
        isFiniteNumber(context?.video_duration_s) && context.video_duration_s > 0 ? context.video_duration_s : null
    const clamp = (seconds: number): number =>
        Math.max(0, videoDuration === null ? seconds : Math.min(seconds, videoDuration))
    const at = isFiniteNumber(sessionSeconds) ? sessionSeconds : 0
    const periods = mappedPeriods(context?.inactivity_periods)
    const last = periods.at(-1)
    if (!last) {
        return clamp(at)
    }
    for (const period of periods) {
        if (at < period.sessionFrom) {
            return clamp(period.videoFrom)
        }
        if (period.sessionTo === null || at <= period.sessionTo) {
            return clamp(videoSecondsInside(period, at))
        }
    }
    return clamp(last.videoTo ?? last.videoFrom)
}
