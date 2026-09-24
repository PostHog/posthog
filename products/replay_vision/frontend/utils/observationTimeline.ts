import type { ObservationSeekbarMark } from './observation'

// Rows are spaced by elapsed time, capped so one quiet stretch can't push the rest off screen.
export const TIMELINE_GAP_PX_PER_SECOND = 0.3
export const TIMELINE_GAP_MAX_PX = 20

export function timelineGapPx(deltaMs: number): number {
    return Math.min(TIMELINE_GAP_MAX_PX, Math.max(0, (deltaMs / 1000) * TIMELINE_GAP_PX_PER_SECOND))
}

/** -1 when playback has not reached the first mark. */
export function currentMarkIndex(marks: ObservationSeekbarMark[], playerTimeMs: number): number {
    let index = -1
    for (let i = 0; i < marks.length; i++) {
        if (marks[i].timestampMs <= playerTimeMs) {
            index = i
        } else {
            break
        }
    }
    return index
}

export function nextMarkAfter(marks: ObservationSeekbarMark[], playerTimeMs: number): ObservationSeekbarMark | null {
    return marks.find((mark) => mark.timestampMs > playerTimeMs) ?? null
}
