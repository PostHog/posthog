import { combineUrl } from 'kea-router'

import { RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { DateRange, NodeKind } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    ChartDisplayType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
    RetentionDashboardDisplayType,
    TrendResult,
} from '~/types'

import {
    getHomeTabAudienceOptions,
    getHomeTabBreakdownOptions,
    getHomeTabChartOptions,
    getHomeTabDashboardTemplate,
    getHomeTabExploreUrl,
    getHomeTabInterval,
    getHomeTabStatQueries,
    getHomeTabStatValue,
    isHomeTabStatBucketInProgress,
} from './homeTabDefaultTiles'
import { homeTabStatTrendKey } from './homeTabQueryKeys'

describe('homeTabDefaultTiles', () => {
    const dateRange: DateRange = { date_from: '-14d', date_to: null }

    it('aggregates each stat on the combined event group', () => {
        const stats = getHomeTabStatQueries(dateRange, true)

        expect(stats.map(({ key, query }) => ({ key, series: query.series[0] }))).toEqual([
            {
                key: 'active_users',
                series: expect.objectContaining({
                    kind: NodeKind.GroupNode,
                    math: BaseMathType.UniqueUsers,
                    nodes: expect.arrayContaining([
                        expect.objectContaining({ event: '$pageview' }),
                        expect.objectContaining({ event: '$screen' }),
                    ]),
                }),
            },
            {
                key: 'sessions',
                series: expect.objectContaining({ kind: NodeKind.GroupNode, math: BaseMathType.UniqueSessions }),
            },
            {
                key: 'new_users',
                series: expect.objectContaining({ kind: NodeKind.GroupNode, math: BaseMathType.FirstTimeForUser }),
            },
            {
                key: 'session_duration',
                series: expect.objectContaining({
                    kind: NodeKind.GroupNode,
                    math: PropertyMathType.Average,
                    math_property: '$session_duration',
                }),
            },
            {
                key: 'daily_active_users',
                series: expect.objectContaining({ kind: NodeKind.GroupNode, math: BaseMathType.UniqueUsers }),
            },
        ])

        expect(
            getHomeTabChartOptions(dateRange, true).find(({ key }) => key === 'weekly_active_users')?.query
        ).toMatchObject({
            source: {
                kind: NodeKind.TrendsQuery,
                series: [expect.objectContaining({ kind: NodeKind.GroupNode, math: BaseMathType.WeeklyActiveUsers })],
            },
        })
    })

    it('averages daily user counts including zero-activity days instead of using period-wide unique users', () => {
        const stat = getHomeTabStatQueries(dateRange, true).find(({ key }) => key === 'daily_active_users')!
        const result = { data: [6, 0, 3], aggregated_value: 7 } as TrendResult
        expect(getHomeTabStatValue(stat, result)).toBe(3)
        expect(getHomeTabStatValue(stat, { ...result, data: [0, 0, 0] })).toBe(0)
        expect(getHomeTabStatValue(stat, { ...result, data: [] })).toBeUndefined()

        const hourlyRange: DateRange = { date_from: '-24h', date_to: null }
        const dailyStat = getHomeTabStatQueries(hourlyRange, true).find(({ key }) => key === 'daily_active_users')!
        expect(dailyStat.query).toMatchObject({
            interval: 'day',
            dateRange: hourlyRange,
            compareFilter: { compare: true },
        })
        expect(
            getHomeTabChartOptions(hourlyRange, true).find(({ key }) => key === 'daily_active_users')?.query.source
        ).toMatchObject({ interval: 'day', dateRange: hourlyRange, compareFilter: { compare: true } })
    })

    it.each(['-7d', '-24h'])('reuses daily user data only when the interval matches for %s', (dateFrom) => {
        const stats = getHomeTabStatQueries({ date_from: dateFrom }, true)
        const activeUsers = stats.find(({ key }) => key === 'active_users')!
        const dailyActiveUsers = stats.find(({ key }) => key === 'daily_active_users')!
        if (dateFrom === '-7d') {
            expect(activeUsers.trendQuery).toBe(dailyActiveUsers.query)
            expect(homeTabStatTrendKey(2, activeUsers)).toBe(homeTabStatTrendKey(2, dailyActiveUsers))
        } else {
            expect(activeUsers.trendQuery?.interval).toBe('hour')
            expect(activeUsers.trendQuery?.compareFilter?.compare).toBe(false)
            expect(homeTabStatTrendKey(2, activeUsers)).not.toBe(homeTabStatTrendKey(2, dailyActiveUsers))
        }
        expect(activeUsers.query.trendsFilter?.display).toBe(ChartDisplayType.BoldNumber)
    })

    it.each([
        [0, 'UTC', '2026-06-28T12:00:00Z', '2026-06-28', true],
        [1, 'UTC', '2026-06-28T12:00:00Z', '2026-06-22', true],
        [0, 'UTC', '2026-06-29T12:00:00Z', '2026-06-21', false],
        [0, 'America/Los_Angeles', '2026-06-29T01:00:00Z', '2026-06-28', true],
        [1, 'America/Los_Angeles', '2026-06-29T01:00:00Z', '2026-06-22', true],
    ])('detects incomplete weeks with week start %s in %s at %s', (weekStartDay, timezone, now, lastDay, expected) => {
        const result = { days: ['2026-06-14', lastDay] } as TrendResult
        expect(isHomeTabStatBucketInProgress(result, 'week', timezone, weekStartDay, dayjs(now))).toBe(expected)
    })

    it('applies the selected range and comparison to stats and charts, including retention', () => {
        const stats = getHomeTabStatQueries(dateRange, false)
        const charts = getHomeTabChartOptions(dateRange, false)

        for (const stat of stats) {
            expect(stat.query.dateRange).toEqual(dateRange)
            expect(stat.query.compareFilter?.compare).toBe(false)
            if (stat.trendQuery) {
                expect(stat.query.trendsFilter?.display).toBe(ChartDisplayType.BoldNumber)
                expect(stat.trendQuery.dateRange).toEqual(dateRange)
                expect(stat.trendQuery.interval).toBe(stat.query.interval)
                expect(stat.trendQuery.series).toEqual(stat.query.series)
                expect(stat.trendQuery.compareFilter?.compare).toBe(false)
                expect(stat.trendQuery.trendsFilter?.display).not.toBe(ChartDisplayType.BoldNumber)
            }
        }

        for (const chart of charts) {
            expect(chart.query.source.dateRange).toEqual(dateRange)
            if (chart.query.source.kind === NodeKind.TrendsQuery) {
                expect(chart.query.source.compareFilter?.compare).toBe(false)
            }
        }

        const retentionQuery = charts.find(({ key }) => key === 'retention')?.query.source
        expect(retentionQuery).toMatchObject({
            kind: NodeKind.RetentionQuery,
            retentionFilter: {
                totalIntervals: 3,
                dashboardDisplay: RetentionDashboardDisplayType.TableOnly,
                retentionType: RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
            },
        })
        const activityEntity = {
            type: 'events',
            properties: [
                {
                    type: PropertyFilterType.EventMetadata,
                    key: 'event',
                    operator: PropertyOperator.In,
                    value: ['$pageview', '$screen'],
                },
            ],
        }
        const retentionFilter = retentionQuery?.kind === NodeKind.RetentionQuery ? retentionQuery.retentionFilter : null
        expect(retentionFilter?.targetEntity).toEqual(activityEntity)
        expect(retentionFilter?.returningEntity).toEqual(activityEntity)
        expect(
            getHomeTabChartOptions({ date_from: '-30d', date_to: null }, true).find(({ key }) => key === 'retention')
                ?.query.source
        ).toMatchObject({ retentionFilter: { totalIntervals: 6 } })
    })

    it('offers a matching trend for every selectable summary metric', () => {
        const statKeys = getHomeTabStatQueries(dateRange, true).map(({ key }) => key)
        const charts = getHomeTabChartOptions(dateRange, true)

        for (const key of statKeys) {
            expect(charts.find((chart) => chart.key === key)?.query.source.kind).toBe(NodeKind.TrendsQuery)
        }
    })

    it.each([
        ['2026-09-01', '2026-09-30', 'week'],
        ['2024-01-01', '2026-01-01', 'month'],
        ['2024-01-01T12:00:00', '2026-01-01T12:00:00', 'month'],
    ])('uses a suitable interval for custom dates %s to %s', (date_from, date_to, interval) => {
        expect(getHomeTabInterval({ date_from, date_to })).toBe(interval)
    })

    it('labels the selected time bucket in activity charts', () => {
        const hourlyChart = getHomeTabChartOptions({ date_from: '-24h', date_to: null }, true).find(
            ({ key }) => key === 'active_users'
        )
        expect(hourlyChart?.description).toContain('each hour')
        expect(hourlyChart?.query.source).toMatchObject({
            interval: 'hour',
            compareFilter: { compare: true },
        })

        const minuteChart = getHomeTabChartOptions({ date_from: '-1h', date_to: null }, false).find(
            ({ key }) => key === 'active_users'
        )
        expect(minuteChart?.description).toContain('each minute')
        expect(minuteChart?.query.source).toMatchObject({ interval: 'minute' })
    })

    it('ranks web pages, mobile screens, and all event names within the selected range', () => {
        const exactRange: DateRange = { date_from: '2026-08-01', date_to: '2026-08-31', explicitDate: true }
        const options = getHomeTabBreakdownOptions(exactRange)

        expect(options.map(({ key }) => key)).toEqual(['top_pages', 'top_screens', 'top_events'])
        expect(options.map(({ query }) => query.source)).toEqual([
            expect.objectContaining({
                dateRange: exactRange,
                series: [expect.objectContaining({ event: '$pageview', math: BaseMathType.TotalCount })],
                trendsFilter: { display: ChartDisplayType.ActionsBarValue },
                breakdownFilter: expect.objectContaining({
                    breakdown: '$pathname',
                    breakdown_type: 'event',
                    breakdown_limit: 8,
                }),
            }),
            expect.objectContaining({
                dateRange: exactRange,
                series: [expect.objectContaining({ event: '$screen', math: BaseMathType.TotalCount })],
                breakdownFilter: expect.objectContaining({ breakdown: '$screen_name', breakdown_type: 'event' }),
            }),
            expect.objectContaining({
                dateRange: exactRange,
                series: [expect.objectContaining({ event: null, math: BaseMathType.TotalCount })],
                breakdownFilter: expect.objectContaining({ breakdown: 'event', breakdown_type: 'event_metadata' }),
            }),
        ])

        for (const option of options) {
            expect(option.query.source.kind).toBe(NodeKind.TrendsQuery)
            if (option.query.source.kind === NodeKind.TrendsQuery) {
                expect(option.query.source.compareFilter?.compare).toBeFalsy()
            }
        }
        const destination = combineUrl(getHomeTabExploreUrl(options[2].query))
        expect(JSON.parse(destination.hashParams.q).source.breakdownFilter.breakdown).toBe('event')
    })

    it('counts web and mobile activity with the series and filters supported by each audience chart', () => {
        const charts = getHomeTabAudienceOptions({ date_from: '-1h', date_to: null })
        const [map, devices] = charts
        expect(charts.map(({ key }) => key)).toEqual(['users_by_country', 'sessions_by_device'])
        expect(map.query.source).toMatchObject({
            series: [
                {
                    kind: NodeKind.GroupNode,
                    math: BaseMathType.UniqueUsers,
                    nodes: [{ event: '$pageview' }, { event: '$screen' }],
                },
            ],
            dateRange: { date_from: '-1h', date_to: null },
            compareFilter: { compare: false },
            trendsFilter: { display: ChartDisplayType.WorldMap },
            breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event', breakdown_limit: 250 },
        })
        expect(devices.query.source).toMatchObject({
            series: [{ math: BaseMathType.UniqueSessions }],
            trendsFilter: { display: ChartDisplayType.ActionsDonut },
            breakdownFilter: { breakdown: '$device_type' },
        })
        for (const chart of charts) {
            const destination = combineUrl(getHomeTabExploreUrl(chart.query))
            expect(JSON.parse(destination.hashParams.q).source).toEqual(JSON.parse(JSON.stringify(chart.query.source)))
        }
    })

    it.each(['active_users', 'retention'])('opens %s in the insight editor with its selected range', (key) => {
        const chart = getHomeTabChartOptions(dateRange, true).find((chart) => chart.key === key)
        expect(chart).toBeTruthy()

        const destination = combineUrl(getHomeTabExploreUrl(chart!.query))
        expect(destination.pathname).toBe('/insights/new')
        const editorQuery = JSON.parse(destination.hashParams.q)
        expect(editorQuery.kind).toBe(NodeKind.InsightVizNode)
        expect(editorQuery.embedded).toBeUndefined()
        expect(editorQuery.source).toEqual(JSON.parse(JSON.stringify(chart!.query.source)))
        expect(editorQuery.source.dateRange).toEqual(dateRange)
    })

    it('copies Home into a dashboard template with saved queries and a non-overlapping layout', () => {
        const { tiles } = getHomeTabDashboardTemplate()

        expect(tiles.map((tile) => tile.type === 'INSIGHT' && tile.name)).toEqual([
            'Weekly active users',
            'Sessions',
            'First-time users',
            'Avg. session duration',
            'Avg. DAU',
            'Daily active users',
            'Top pages',
            'Top screens',
            'Top events',
            'New user retention',
            'Active users by country',
            'Sessions by device',
        ])
        const cells = new Set<string>()
        for (const tile of tiles) {
            expect(tile.type === 'INSIGHT' && tile.query).toMatchObject({ kind: NodeKind.InsightVizNode })
            expect(tile.type === 'INSIGHT' && tile.query).not.toHaveProperty('embedded')
            const { x, y, w, h } = tile.layouts!.sm!
            expect(x + w).toBeLessThanOrEqual(12)
            for (let column = x; column < x + w; column++) {
                for (let row = y; row < y + h; row++) {
                    expect(cells.has(`${column},${row}`)).toBe(false)
                    cells.add(`${column},${row}`)
                }
            }
        }
        expect(tiles.slice(0, 5).map((tile) => tile.type === 'INSIGHT' && tile.query)).toMatchObject([
            {
                source: {
                    series: [{ math: BaseMathType.WeeklyActiveUsers }],
                    interval: 'day',
                    trendsFilter: { display: ChartDisplayType.Metric, metricSummary: 'latest' },
                },
            },
            { source: { trendsFilter: { display: ChartDisplayType.Metric, metricSummary: 'total' } } },
            { source: { trendsFilter: { display: ChartDisplayType.Metric, metricSummary: 'total' } } },
            {
                source: {
                    trendsFilter: {
                        display: ChartDisplayType.Metric,
                        metricSummary: 'average',
                        aggregationAxisFormat: 'duration',
                    },
                },
            },
            {
                source: {
                    interval: 'day',
                    trendsFilter: { display: ChartDisplayType.Metric, metricSummary: 'average' },
                },
            },
        ])
    })
})
