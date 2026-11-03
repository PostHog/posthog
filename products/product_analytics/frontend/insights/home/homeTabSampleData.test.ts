import tk from 'timekeeper'

import { getHomeTabChartOptions, getHomeTabStatQueries } from './homeTabDefaultTiles'
import { getHomeTabSampleData, getHomeTabSampleStatData } from './homeTabSampleData'

describe('homeTabSampleData', () => {
    beforeEach(() => tk.freeze(new Date('2026-10-14T12:00:00Z')))
    afterEach(() => tk.reset())

    it.each([
        ['-1dStart', '-1dEnd', '2026-10-13T22:00:00.000Z'],
        ['-1wStart', '-1wEnd', '2026-10-09T00:00:00.000Z'],
        ['-1mStart', '-1mEnd', '2026-09-29T00:00:00.000Z'],
        ['2026-10-01', '2026-10-07', '2026-10-06T00:00:00.000Z'],
        ['-7d', null, '2026-10-13T00:00:00.000Z'],
        ['-7d', undefined, '2026-10-13T00:00:00.000Z'],
    ])('generates sample timestamps for %s to %s', (date_from, date_to, lastBucket) => {
        const dateRange = { date_from, date_to }
        const stat = getHomeTabStatQueries(dateRange, true).find(({ key }) => key === 'sessions')!
        const response = getHomeTabSampleStatData(stat.key, stat.query)

        expect(response.results).toHaveLength(2)
        for (const result of response.results) {
            expect(result.days).toHaveLength(result.data.length)
            expect(result.days[result.days.length - 1]).toBe(lastBucket)
        }

        const chart = getHomeTabChartOptions(dateRange, true).find(({ key }) => key === 'sessions')!
        expect(getHomeTabSampleData(chart)).toEqual(response)
    })
})
