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

    it('keeps the order the backend ranked, which weighs scale as well as ratio', () => {
        // anomaly.py ranks by a magnitude blending ratio with size, so a rounding-error series that
        // tripled does not outrank a large one that moved a lot. Re-sorting on percentage here would
        // put the noise first, and it is the row a user clicks to narrow the chart.
        const rows = topMoverRows([
            mover({
                key: 'service_name',
                label: 'checkout',
                baseline_value: 5000,
                anomaly_value: 6000,
                change_ratio: 1.2,
            }),
            mover({ label: 'debug-sidecar', baseline_value: 0.2, anomaly_value: 1, change_ratio: 5 }),
        ])

        expect(rows.map((row) => row.label)).toEqual(['checkout', 'debug-sidecar'])
    })

    it('reports how far each label value moved', () => {
        const rows = topMoverRows([mover({ baseline_value: 100, anomaly_value: 300, change_ratio: 3 })])
        expect(rows[0]).toMatchObject({ percent: 200, direction: 'up' })
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

    it('marks a mover with no label value as unfilterable', () => {
        // A group-by on a key some series lack yields '', which no equality filter can express.
        // Left clickable it appends a chip that filters nothing and cannot be deduped away.
        const rows = topMoverRows([mover({ key: 'service_name', label: '' })])
        expect(rows[0]).toMatchObject({ label: '', isFilterable: false })
    })

    it('returns nothing when the metric has no labels to attribute to', () => {
        expect(topMoverRows([])).toEqual([])
    })
})
