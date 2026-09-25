import type { ObservationSeekbarMark } from './observation'
import { TIMELINE_GAP_MAX_PX, currentMarkIndex, nextMarkAfter, timelineGapPx } from './observationTimeline'

const mark = (timestampMs: number): ObservationSeekbarMark => ({ timestampMs, entries: [], flagged: false })
const marks = [mark(10_000), mark(42_000), mark(42_000), mark(90_000)]

describe('observationTimeline', () => {
    it.each<[string, number, number]>([
        ['no gap', 0, 0],
        ['scales with elapsed seconds', 10_000, 3],
        ['caps at the ceiling', 600_000, TIMELINE_GAP_MAX_PX],
        ['never negative', -5_000, 0],
    ])('timelineGapPx: %s', (_, deltaMs, expected) => {
        expect(timelineGapPx(deltaMs)).toBe(expected)
    })

    it.each<[string, number, number, number | null]>([
        ['before the first mark', 0, -1, 10_000],
        ['exactly on a mark', 42_000, 2, 90_000],
        ['between marks', 50_000, 2, 90_000],
        ['past the last mark', 100_000, 3, null],
    ])('playhead %s', (_, playerTimeMs, expectedIndex, expectedNextMs) => {
        expect(currentMarkIndex(marks, playerTimeMs)).toBe(expectedIndex)
        expect(nextMarkAfter(marks, playerTimeMs)?.timestampMs ?? null).toBe(expectedNextMs)
    })
})
