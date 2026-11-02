import { rangeContent, type TooltipContent, tooltipContent, tooltipPoint } from './chartSeries'
import type { ChartSeries } from './types'

const day = (date: number): number => new Date(2026, 9, date).getTime()
const format = (value: number): string => value.toLocaleString('en-US')

const current: ChartSeries = {
    key: 'dau',
    label: 'Daily active users',
    color: '#1D4AFF',
    points: [
        { at: day(13), value: 1071 },
        { at: day(14), value: 1204 },
    ],
    incompleteFrom: 1,
}
const previous: ChartSeries = {
    key: 'dau-previous',
    label: 'Previous period',
    color: '#1D4AFF',
    compareOf: 'dau',
    points: [
        { at: new Date(2026, 8, 29).getTime(), value: 990 },
        { at: new Date(2026, 8, 30).getTime(), value: 1071 },
    ],
}
const platforms: ChartSeries[] = ['iOS', 'Android', 'Web', 'Desktop', 'Watch'].map((label, index) => ({
    key: label,
    label,
    color: '#000000',
    points: [{ at: day(13), value: (index + 1) * 10 }],
}))

describe('chartSeries', () => {
    test.each<[string, ChartSeries[], string[], number, Partial<TooltipContent>]>([
        [
            'one series shows its previous period and the change',
            [current, previous],
            [],
            0,
            { compare: { previous: 'Previous: 990 (Sep 29)', change: '+81 (+8.2%)' }, note: null },
        ],
        [
            'the bucket in progress says how fresh it is',
            [current, previous],
            [],
            1,
            { header: 'Wed, Oct 14, 2026', note: 'In progress. Data until 14:32.' },
        ],
        ['many series show the four highest and count the rest', platforms, [], 0, { more: 1, compare: null }],
        ['hidden series leave the tooltip', platforms, ['Watch', 'Desktop'], 0, { more: 0 }],
    ])('tooltipContent: %s', (_, series, hidden, index, expected) => {
        const point = tooltipPoint(series, hidden, index, 'day')
        if (!point) {
            throw new Error('expected a point')
        }
        const content = tooltipContent(point, {
            formatValue: format,
            compact: false,
            maxRows: 4,
            dataUntil: new Date(2026, 9, 14, 14, 32).getTime(),
        })
        expect(content).toMatchObject(expected)
        expect(content.rows.map((row) => row.value)).toEqual(
            [...content.rows.map((row) => row.value)].sort((a, b) => b - a)
        )
        expect(content.rows.some((row) => hidden.includes(row.key))).toBe(false)
    })

    test('rangeContent puts the earlier marker first and skips the previous period', () => {
        expect(rangeContent([current, previous], [], 1, 0, 'day', format)).toEqual({
            header: 'Oct 13 → Oct 14',
            rows: [
                {
                    key: 'dau',
                    label: 'Daily active users',
                    color: '#1D4AFF',
                    values: '1,071 → 1,204',
                    change: '+133 (+12.4%)',
                },
            ],
        })
    })
})
