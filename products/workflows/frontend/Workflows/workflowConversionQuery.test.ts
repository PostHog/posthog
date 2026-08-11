import api from 'lib/api'

import { loadWorkflowConversionSeries } from './workflowConversionQuery'

describe('loadWorkflowConversionSeries', () => {
    let queryHogQL: jest.SpyInstance

    const baseRequest = {
        workflowId: 'flow-1',
        dateFrom: '2026-01-01T00:00:00.000Z',
        dateTo: '2026-01-03T00:00:00.000Z',
        interval: 'day' as const,
        windowMinutes: null,
    }

    beforeEach(() => {
        queryHogQL = jest.spyOn(api, 'queryHogQL').mockResolvedValue({
            results: [
                [
                    ['2026-01-01', '2026-01-02'],
                    [4, 6],
                    [1, 3],
                ],
            ],
        } as any)
    })

    afterEach(() => {
        queryHogQL.mockRestore()
    })

    it('maps the response columns onto labels, enrolled and converted', async () => {
        // The three columns are positional, so a reordered SELECT would silently swap the
        // denominator and the numerator rather than fail.
        const result = await loadWorkflowConversionSeries(baseRequest, 'UTC')

        expect(result.enrolled).toEqual([4, 6])
        expect(result.converted).toEqual([1, 3])
        expect(result.labels).toEqual(['2026-01-01', '2026-01-02'])
    })

    it('returns empty series when the query matches nothing', async () => {
        queryHogQL.mockResolvedValue({ results: [] } as any)

        expect(await loadWorkflowConversionSeries(baseRequest, 'UTC')).toEqual({
            labels: [],
            enrolled: [],
            converted: [],
        })
    })

    it.each([
        ['no window', null, false],
        ['a zero window', 0, false],
        ['a 60 minute window', 60, true],
    ])('applies the attribution window for %s', async (_name, windowMinutes, expectClause) => {
        await loadWorkflowConversionSeries({ ...baseRequest, windowMinutes }, 'UTC')

        const query = queryHogQL.mock.calls[0][0] as string
        expect(query.includes('toIntervalMinute(60)')).toBe(expectClause)
    })
})
