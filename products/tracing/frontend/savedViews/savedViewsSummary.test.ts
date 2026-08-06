import { getTracingFiltersSummaryLines } from './savedViewsSummary'

describe('getTracingFiltersSummaryLines', () => {
    it('returns no lines for empty filters', () => {
        expect(getTracingFiltersSummaryLines({})).toEqual([])
    })

    it('summarizes a date range with both bounds', () => {
        const lines = getTracingFiltersSummaryLines({ dateRange: { date_from: '-24h', date_to: '-1h' } })
        expect(lines).toEqual([{ label: 'Date range', value: '-24h → -1h' }])
    })

    it('summarizes a relative date range with only date_from', () => {
        const lines = getTracingFiltersSummaryLines({ dateRange: { date_from: '-1h', date_to: null } })
        expect(lines).toEqual([{ label: 'Date range', value: '-1h' }])
    })

    it('uses singular/plural service labels', () => {
        expect(getTracingFiltersSummaryLines({ serviceNames: ['api'] })).toEqual([{ label: 'Service', value: 'api' }])
        expect(getTracingFiltersSummaryLines({ serviceNames: ['api', 'worker'] })).toEqual([
            { label: 'Services', value: 'api, worker' },
        ])
    })

    it('truncates long service lists with a +N more suffix', () => {
        const lines = getTracingFiltersSummaryLines({ serviceNames: ['a', 'b', 'c', 'd', 'e'] })
        expect(lines).toEqual([{ label: 'Services', value: 'a, b, c +2 more' }])
    })

    it('summarizes attribute filters from the filter group', () => {
        const filterGroup = {
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [{ key: 'http.status_code', value: '500', type: 'span', operator: 'exact' }],
                },
            ],
        }
        const lines = getTracingFiltersSummaryLines({ filterGroup })
        expect(lines).toEqual([{ label: 'Filter', value: 'http.status_code=500' }])
    })

    it('includes attribute filters from every top-level group, not just the first', () => {
        const filterGroup = {
            type: 'AND',
            values: [
                { type: 'AND', values: [{ key: 'a', value: '1', type: 'span', operator: 'exact' }] },
                { type: 'AND', values: [{ key: 'b', value: '2', type: 'span', operator: 'exact' }] },
            ],
        }
        const lines = getTracingFiltersSummaryLines({ filterGroup })
        expect(lines).toEqual([{ label: 'Filters', value: 'a=1, b=2' }])
    })

    it('maps view mode and sort to readable lines', () => {
        const lines = getTracingFiltersSummaryLines({
            viewMode: 'spans',
            orderBy: 'duration',
            orderDirection: 'ASC',
        })
        expect(lines).toEqual([
            { label: 'View', value: 'Spans' },
            { label: 'Sort', value: 'duration (ascending)' },
        ])
    })

    it('combines all filter types in order', () => {
        const lines = getTracingFiltersSummaryLines({
            dateRange: { date_from: '-1h', date_to: null },
            serviceNames: ['api'],
            filterGroup: {
                type: 'AND',
                values: [{ type: 'AND', values: [{ key: 'env', value: 'prod', type: 'span', operator: 'exact' }] }],
            },
            viewMode: 'traces',
            orderBy: 'timestamp',
            orderDirection: 'DESC',
        })
        expect(lines.map((l) => l.label)).toEqual(['Date range', 'Service', 'Filter', 'View', 'Sort'])
    })
})
