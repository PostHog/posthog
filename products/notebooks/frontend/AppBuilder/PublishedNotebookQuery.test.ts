import { rowForChartSelection } from './PublishedNotebookQuery'

const result = {
    columns: ['week', 'region', 'signups'],
    results: [
        ['2026-10-12', 'East', 22],
        ['2026-10-12', 'West', 105],
    ],
}

it('passes all fields for the selected chart point to the binding', () => {
    expect(rowForChartSelection(result, 'week', '2026-10-12', 1)).toEqual({
        week: '2026-10-12',
        region: 'West',
        signups: 105,
    })
})

it('matches the selected series at a shared x coordinate and skips ambiguous aggregates', () => {
    expect(rowForChartSelection(result, 'week', '2026-10-12', 0, 'region', 'West')).toEqual({
        week: '2026-10-12',
        region: 'West',
        signups: 105,
    })
    const aggregate = { ...result, results: [...result.results, ['2026-10-12', 'West', 47]] }
    expect(rowForChartSelection(aggregate, 'week', '2026-10-12', 0, 'region', 'West')).toBeNull()
})
