import { buildTimePositioner } from './buildTimePositioner'

describe('buildTimePositioner', () => {
    // One bucket every hour, band centers 20px apart starting at x=10 — the first bucket's
    // timestamp sits at its left edge (x=0), not its center (x=10), per the convention this
    // positioner implements.
    const HOUR_MS = 60 * 60 * 1000
    const dates = [0, 1, 2, 3].map((i) => new Date(i * HOUR_MS))
    const labels = dates.map((d) => d.toISOString())
    const scaleX = (label: string): number | undefined => {
        const index = labels.indexOf(label)
        return index === -1 ? undefined : 10 + index * 20
    }

    it('places an event exactly between two bucket starts at the midpoint', () => {
        const positionAt = buildTimePositioner(dates, labels, scaleX)
        expect(positionAt).not.toBeNull()
        // Bucket 0's timestamp sits at its left edge (x=0, band center 10 minus half the 20px
        // step); bucket 1's left edge is at x=20. Halfway in time between them lands at x=30.
        expect(positionAt?.(dates[1].getTime() + HOUR_MS / 2)).toBe(30)
    })

    it('extrapolates for an event before the first bucket', () => {
        const positionAt = buildTimePositioner(dates, labels, scaleX)
        expect(positionAt?.(dates[0].getTime() - HOUR_MS)).toBe(-20)
    })

    it('extrapolates for an event after the last bucket', () => {
        const positionAt = buildTimePositioner(dates, labels, scaleX)
        expect(positionAt?.(dates[3].getTime() + HOUR_MS)).toBe(80)
    })

    it('returns null for a single-bucket chart', () => {
        expect(buildTimePositioner([dates[0]], [labels[0]], scaleX)).toBeNull()
    })

    it('returns null when adjacent buckets resolve to the same x (zero step)', () => {
        expect(buildTimePositioner(dates, labels, () => 10)).toBeNull()
    })

    it('returns null when adjacent buckets share a timestamp (zero bucketMs)', () => {
        const flatDates = [dates[0], dates[0], dates[2], dates[3]]
        expect(buildTimePositioner(flatDates, labels, scaleX)).toBeNull()
    })

    it('returns null when the scale has not resolved a label yet', () => {
        expect(buildTimePositioner(dates, labels, () => undefined)).toBeNull()
    })
})
