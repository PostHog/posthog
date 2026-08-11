import { buildTimePositioner } from './buildTimePositioner'

describe('buildTimePositioner', () => {
    // Hourly buckets, band centers 20px apart from x=10. A bucket's timestamp is its left edge
    // (x=0), not its center.
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
        // Left edges are x=0 and x=20, so halfway in time between them lands at x=30.
        expect(positionAt?.(dates[1].getTime() + HOUR_MS / 2)).toBe(30)
    })

    it('extrapolates for an event before the first bucket', () => {
        const positionAt = buildTimePositioner(dates, labels, scaleX)
        expect(positionAt?.(dates[0].getTime() - HOUR_MS)).toBe(-20)
    })

    it.each([
        { name: 'a single-bucket chart', dates: [dates[0]], labels: [labels[0]], scale: scaleX },
        { name: 'adjacent buckets at the same x', dates, labels, scale: () => 10 },
        {
            name: 'adjacent buckets sharing a timestamp',
            dates: [dates[0], dates[0], dates[2], dates[3]],
            labels,
            scale: scaleX,
        },
        { name: 'a scale that has not resolved a label', dates, labels, scale: () => undefined },
    ])('returns null for $name', ({ dates: d, labels: l, scale }) => {
        expect(buildTimePositioner(d, l, scale)).toBeNull()
    })
})
