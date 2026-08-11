import { type LabelSpreadItem, spreadLabels } from './spreadLabels'

describe('spreadLabels', () => {
    const MIN_GAP = 2
    const MIN = 0
    const MAX = 200

    function overlaps(items: LabelSpreadItem[], centers: number[]): boolean {
        const sorted = centers
            .map((center, index) => ({ center, halfWidth: items[index].halfWidth }))
            .sort((a, b) => a.center - b.center)
        return sorted.some(
            (item, i) => i > 0 && item.center - item.halfWidth < sorted[i - 1].center + sorted[i - 1].halfWidth
        )
    }

    // "First seen" and "Last seen" land in the same bucket on a short-lived issue, so both pills
    // want the same x. Without the second (right-to-left) pass the clamp at `max` piles them back
    // on top of each other.
    it.each([
        {
            name: 'identical centers',
            items: [
                { center: 100, halfWidth: 25 },
                { center: 100, halfWidth: 25 },
            ],
        },
        {
            name: 'both pinned at the right edge',
            items: [
                { center: 200, halfWidth: 30 },
                { center: 198, halfWidth: 30 },
            ],
        },
        {
            name: 'both pinned at the left edge',
            items: [
                { center: 0, halfWidth: 30 },
                { center: 2, halfWidth: 30 },
            ],
        },
        {
            name: 'three crowded labels',
            items: [
                { center: 90, halfWidth: 28 },
                { center: 100, halfWidth: 28 },
                { center: 110, halfWidth: 28 },
            ],
        },
    ])('separates $name', ({ items }) => {
        const centers = spreadLabels(items, MIN_GAP, MIN, MAX)
        expect(overlaps(items, centers)).toBe(false)
        expect(Math.max(...centers.map((c, i) => c + items[i].halfWidth))).toBeLessThanOrEqual(MAX)
    })

    it('preserves left-to-right order when spreading', () => {
        const items = [
            { center: 110, halfWidth: 28 },
            { center: 90, halfWidth: 28 },
        ]
        const [right, left] = spreadLabels(items, MIN_GAP, MIN, MAX)
        expect(left).toBeLessThan(right)
    })

    it('leaves labels that already fit exactly where they are', () => {
        const items = [
            { center: 30, halfWidth: 10 },
            { center: 150, halfWidth: 10 },
        ]
        expect(spreadLabels(items, MIN_GAP, MIN, MAX)).toEqual([30, 150])
    })
})
