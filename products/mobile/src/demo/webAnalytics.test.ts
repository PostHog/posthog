import {
    type WebQueryWindow,
    webActiveHoursQuery,
    webBreakdownQuery,
    webOverviewQuery,
    webRetentionQuery,
    webTrendQuery,
} from '@/api/webAnalytics'
import { webAnalyticsInterval } from '@/features/views/webAnalytics/interval'
import { webActiveHoursSnapshot, webBreakdownSnapshot, webInsightSnapshot } from '@/model/adapters/webAnalytics'
import { breakdownFilter, WEB_TILES } from '@/model/adapters/webAnalyticsBreakdowns'
import { webOverviewSnapshot } from '@/model/adapters/webOverview'
import type { WebTrendMetric } from '@/model/views'

import { demoWebOverviewResponse, demoWebQueryResponse } from './webAnalytics'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

const ANCHOR = Date.parse('2026-10-14T12:00:00Z')
const CONTEXT = { readAt: ANCHOR, serverNow: ANCHOR }

function windowFor(dateFrom: string): WebQueryWindow {
    return {
        dateFrom,
        dateTo: null,
        interval: webAnalyticsInterval({ date_from: dateFrom, date_to: null }, ANCHOR),
        properties: [],
    }
}

function trendValues(window: WebQueryWindow, metric: WebTrendMetric): number[] {
    const query = webTrendQuery({ ...window, metric })
    const snapshot = webInsightSnapshot(query, metric, demoWebQueryResponse(query, ANCHOR), undefined, CONTEXT)
    const current = snapshot.allSeries.find((series) => series.compare === 'current')
    const previous = snapshot.allSeries.find((series) => series.compare === 'previous')
    expect(previous?.points.length).toBe(current?.points.length)
    return current?.points.map((point) => point.value) ?? []
}

describe('web analytics demo', () => {
    test.each(['dStart', '-24h', '-7d', '-90d', '-180d'])('every card draws for %s', (dateFrom) => {
        const window = windowFor(dateFrom)

        const visitors = trendValues(window, 'visitors')
        const sessions = trendValues(window, 'sessions')
        const views = trendValues(window, 'views')
        expect(visitors.length).toBeGreaterThan(0)
        visitors.forEach((value, index) => {
            expect(sessions[index]).toBeGreaterThanOrEqual(value)
            expect(views[index]).toBeGreaterThanOrEqual(sessions[index] ?? 0)
        })
        for (const metric of ['session duration', 'bounce rate'] as const) {
            expect(trendValues(window, metric).every(Number.isFinite)).toBe(true)
        }
        for (const breakdown of WEB_TILES.flatMap((tile) => tile.tabs)) {
            const query = webBreakdownQuery({ ...window, breakdown, limit: 10 })
            const table = webBreakdownSnapshot(breakdown, demoWebQueryResponse(query, ANCHOR), undefined, ANCHOR)
            expect([breakdown, table.rows.length > 0]).toEqual([breakdown, true])
        }
        const retentionQuery = webRetentionQuery(window)
        const retention = webInsightSnapshot(
            retentionQuery,
            'Retention',
            demoWebQueryResponse(retentionQuery, ANCHOR),
            undefined,
            CONTEXT
        )
        expect(retention.retention?.cohorts.length).toBe(5)
        const hours = webActiveHoursSnapshot(
            demoWebQueryResponse(webActiveHoursQuery(window), ANCHOR),
            undefined,
            ANCHOR
        )
        expect(hours.total).toBeGreaterThan(0)
    })

    test('a row filter narrows the overview and the table to that row', () => {
        const window = windowFor('-7d')
        const pathQuery = webBreakdownQuery({ ...window, breakdown: 'Page', limit: 10 })
        const pricing = webBreakdownSnapshot(
            'Page',
            demoWebQueryResponse(pathQuery, ANCHOR),
            undefined,
            ANCHOR
        ).rows.find((row) => row.label === '/pricing')
        const properties = breakdownFilter('Page', '/pricing')?.properties ?? []
        const filtered = { ...window, properties }

        const overview = webOverviewSnapshot(
            demoWebOverviewResponse(webOverviewQuery({ ...filtered, compare: true }), ANCHOR),
            undefined,
            ANCHOR
        )
        const filteredQuery = webBreakdownQuery({ ...filtered, breakdown: 'Page', limit: 10 })
        const table = webBreakdownSnapshot('Page', demoWebQueryResponse(filteredQuery, ANCHOR), undefined, ANCHOR)

        expect(overview.metrics.find((metric) => metric.key === 'visitors')?.value).toBe(pricing?.value)
        expect(table.rows.map((row) => row.label)).toEqual(['/pricing'])
    })
})
