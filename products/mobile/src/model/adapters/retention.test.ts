import { retentionView } from './retention'

const NOW = Date.parse('2026-10-14T12:00:00Z')

function retention(reference?: string): unknown {
    return {
        kind: 'InsightVizNode',
        source: { kind: 'RetentionQuery', retentionFilter: { period: 'Week', retentionReference: reference } },
    }
}

// Like the server, the last cohort answers every week, including two that have not started yet.
const RESULT = [
    {
        date: '2026-09-28T00:00:00Z',
        label: 'Week 0',
        values: [
            { count: 200, label: 'Week 0' },
            { count: 100, label: 'Week 1' },
            { count: 50, label: 'Week 2' },
            { count: 0, label: 'Week 3' },
        ],
    },
    {
        date: '2026-10-05T00:00:00Z',
        label: 'Week 1',
        values: [
            { count: 80, label: 'Week 0' },
            { count: 20, label: 'Week 1' },
            { count: 0, label: 'Week 2' },
            { count: 0, label: 'Week 3' },
        ],
    },
]

describe('retentionView', () => {
    test.each<[string, string | undefined, number[][]]>([
        [
            'the cohort size',
            undefined,
            [
                [100, 50, 25],
                [100, 25],
            ],
        ],
        [
            'the period before',
            'previous',
            [
                [100, 50, 50],
                [100, 25],
            ],
        ],
    ])('leaves out periods that have not started and takes percents of %s', (_name, reference, percents) => {
        const view = retentionView(retention(reference), RESULT, NOW)

        expect(view?.periodLabels).toEqual(['Week 0', 'Week 1', 'Week 2', 'Week 3'])
        expect(view?.cohorts.map((cohort) => cohort.cells.map((cell) => cell.percent))).toEqual(percents)
    })
})
