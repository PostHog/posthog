import { topMoverRows } from './metricsAnomaly'

describe('topMoverRows', () => {
    const mover = (overrides: Record<string, unknown> = {}): any => ({
        key: 'pod',
        label: 'api-7f9',
        baseline_value: 100,
        anomaly_value: 150,
        change_ratio: 1.5,
        ...overrides,
    })

    it('reports how far each label value moved, largest first', () => {
        const rows = topMoverRows([
            mover({ label: 'api-1', baseline_value: 100, anomaly_value: 110, change_ratio: 1.1 }),
            mover({ label: 'api-2', baseline_value: 100, anomaly_value: 300, change_ratio: 3 }),
        ])

        expect(rows.map((row) => [row.label, row.percent, row.direction])).toEqual([
            ['api-2', 200, 'up'],
            ['api-1', 10, 'up'],
        ])
    })

    it('reads a drop as a drop rather than a negative rise', () => {
        const rows = topMoverRows([mover({ baseline_value: 100, anomaly_value: 25, change_ratio: 0.25 })])
        expect(rows[0]).toMatchObject({ percent: 75, direction: 'down' })
    })

    it('calls a label value that did not exist before new, instead of an infinite rise', () => {
        // The backend yields the anomaly value itself for a zero baseline, so a ratio here is
        // meaningless — "500% up" from nothing is noise, "new" is the actual finding.
        const rows = topMoverRows([mover({ baseline_value: 0, anomaly_value: 42, change_ratio: 42 })])
        expect(rows[0]).toMatchObject({ isNew: true, direction: 'up' })
    })

    it('ranks a newly appeared value above a merely larger one', () => {
        const rows = topMoverRows([
            mover({ label: 'steady', baseline_value: 100, anomaly_value: 400, change_ratio: 4 }),
            mover({ label: 'brand-new', baseline_value: 0, anomaly_value: 42, change_ratio: 42 }),
        ])
        expect(rows[0].label).toBe('brand-new')
    })

    it('returns nothing when the metric has no labels to attribute to', () => {
        expect(topMoverRows([])).toEqual([])
    })
})
