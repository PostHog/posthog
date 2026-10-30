import { create } from 'zustand'

import type { ActorsAtPointInput, ActorsResponseApi } from '@/api/actors'
import type { DashboardApi, DashboardBasicApi, DashboardTileApi } from '@/api/dashboards'
import type { InsightApi, InsightBasicApi } from '@/api/insights'
import type { FileSystemShortcutApi, ShortcutInput } from '@/api/shortcuts'
import type { WebOverviewResponseApi } from '@/api/webAnalytics'
import { asRecord } from '@/lib/records'
import type { DeviceRecentEntry, PinDisplay } from '@/model/views'

import { useDemoMode } from './demoMode'

// Views demo data. Every name, number and email is invented. Responses have the API shapes, so demo mode runs through
// the same adapters, refresh rules and status line as live mode. Ids are stable because the Argent flow selects by them.

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** How old the demo numbers are when the demo starts: "Updated 42 min ago". */
const DEMO_DATA_AGE_MS = 42 * MINUTE
/** A demo read takes this long, so "Updating…" shows. */
export const DEMO_READ_MS = 450

export const DEMO_DASHBOARD_KPIS = 'demo-dash-kpis'
export const DEMO_DASHBOARD_GROWTH = 'demo-dash-growth'
export const DEMO_DASHBOARD_SQL = 'demo-dash-sql'
export const DEMO_INSIGHT_SIGNUPS = 'demo-ins-signups'
export const DEMO_INSIGHT_DAU = 'demo-ins-dau'
export const DEMO_INSIGHT_CHECKOUT = 'demo-ins-checkout'
export const DEMO_INSIGHT_RETENTION = 'demo-ins-retention'
export const DEMO_INSIGHT_BROWSERS = 'demo-ins-browsers'
export const DEMO_INSIGHT_SQL_PAGES = 'demo-ins-sql-pages'
export const DEMO_INSIGHT_SQL_SIGNUPS = 'demo-ins-sql-signups'
export const DEMO_INSIGHT_SQL_REVENUE = 'demo-ins-sql-revenue'
export const DEMO_INSIGHT_SQL_COUNTRIES = 'demo-ins-sql-countries'

type JsonRecord = Record<string, unknown>

type DemoSqlCell = string | number

/** A SQL result: `[column, ClickHouse type]` per column, and the rows for a window. */
interface DemoSqlResult {
    types: [string, string][]
    rows: (window: DemoWindow, anchor: Date) => DemoSqlCell[][]
}

interface DemoInsightDef {
    id: number
    shortId: string
    name: string
    description: string
    query: JsonRecord
    /** The value for one day; `daysBack` is 0 for today. */
    perDay?: (daysBack: number, weekday: number) => number
    /** A big number over a window of this many days. */
    aggregate?: (windowDays: number) => number
    /** A SQL insight's columns and rows. */
    sql?: DemoSqlResult
    /** Funnel steps over 30 days, scaled to the window. `medianSeconds` is the time from the step before. */
    funnel?: { name: string; count: number; medianSeconds: number | null }[]
    /** Weekly cohorts: the size of an average cohort and the percent that comes back in each week after. */
    retention?: { cohortSize: number; curve: number[] }
    /** Totals per breakdown value: the value's share of `perDay` summed over the window. */
    breakdown?: { value: string; share: number }[]
}

function noise(day: number, salt: number): number {
    const value = Math.sin((day + 1) * 12.9898 + salt * 78.233) * 43_758.5453
    return value - Math.floor(value)
}

/** Daily values around `base` with quieter weekends and one clear dip nine days back. */
function daily(base: number, salt: number, spread = 0.16): (daysBack: number, weekday: number) => number {
    return (daysBack, weekday) => {
        const weekend = weekday === 0 || weekday === 6 ? 0.72 : 1
        const dip = daysBack === 9 ? 0.58 : 1
        const trend = 1 - daysBack * 0.002
        return Math.round(base * weekend * dip * trend * (1 - spread / 2 + noise(daysBack, salt) * spread))
    }
}

function trendsQuery(options: {
    event: string
    math?: string
    display: string
    dateFrom: string
    axisFormat?: string
}): JsonRecord {
    const { event, math, display, dateFrom, axisFormat } = options
    return {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'day',
            series: [{ kind: 'EventsNode', event, name: event, ...(math ? { math } : {}) }],
            trendsFilter: { display, ...(axisFormat ? { aggregationAxisFormat: axisFormat } : {}) },
            dateRange: { date_from: dateFrom, date_to: null },
        },
    }
}

function sqlQuery(query: string, extra: JsonRecord = {}, dateFrom?: string): JsonRecord {
    return {
        kind: 'DataVisualizationNode',
        source: {
            kind: 'HogQLQuery',
            query,
            ...(dateFrom ? { filters: { dateRange: { date_from: dateFrom, date_to: null } } } : {}),
        },
        ...extra,
    }
}

const DEMO_SQL_PAGES: DemoSqlCell[][] = [
    ['example.com/', 12_000, 8400],
    ['example.com/pricing', 6400, 4100],
    ['example.com/docs/getting-started', 5200, 3000],
    ['example.com/blog/hello-world', 3800, 2900],
    ['example.com/signup', 3000, 2600],
    ['example.com/changelog', 2200, 1500],
    ['example.com/about', 1600, 1300],
    ['example.com/careers', 900, 700],
]

// Six columns, wider than a phone, so the table pins its first column. `conversion` is a fraction, as SQL returns it.
const DEMO_SQL_COUNTRIES: DemoSqlCell[][] = [
    ['United States', 4200, 1890, 0.45, 340, '2023-02-01'],
    ['Germany', 1800, 900, 0.5, 280, '2023-03-15'],
    ['United Kingdom', 1500, 600, 0.4, 410, '2023-02-20'],
    ['India', 1300, 390, 0.3, 520, '2023-06-01'],
    ['Brazil', 900, 315, 0.35, 460, '2024-01-10'],
    ['France', 800, 360, 0.45, 300, '2023-04-05'],
    ['Canada', 700, 280, 0.4, 350, '2023-05-12'],
    ['Japan', 500, 250, 0.5, 600, '2024-09-30'],
]

const signupsPerDay = daily(128, 1)

const DEMO_INSIGHTS: DemoInsightDef[] = [
    {
        id: 9101,
        shortId: DEMO_INSIGHT_SIGNUPS,
        name: 'Signups',
        description: 'New accounts per day.',
        query: trendsQuery({ event: 'user signed up', display: 'ActionsLineGraph', dateFrom: '-14d' }),
        perDay: daily(128, 1),
    },
    {
        id: 9102,
        shortId: DEMO_INSIGHT_DAU,
        name: 'Daily active users',
        description: 'People who viewed a page each day.',
        query: trendsQuery({ event: '$pageview', math: 'dau', display: 'ActionsLineGraph', dateFrom: '-14d' }),
        perDay: daily(1840, 2, 0.1),
    },
    {
        id: 9103,
        shortId: 'demo-ins-wau',
        name: 'Weekly active users',
        description: 'People active in the last seven days.',
        query: trendsQuery({ event: '$pageview', math: 'weekly_active', display: 'BoldNumber', dateFrom: '-7d' }),
        aggregate: (windowDays) => Math.round(6420 * Math.min(1.6, Math.max(0.4, windowDays / 8) ** 0.35)),
    },
    {
        id: 9104,
        shortId: 'demo-ins-pageviews',
        name: 'Pageviews',
        description: 'Every page view on the marketing site and the app.',
        query: trendsQuery({ event: '$pageview', display: 'ActionsBar', dateFrom: '-7d' }),
        perDay: daily(9600, 4),
    },
    {
        id: 9105,
        shortId: 'demo-ins-paying',
        name: 'Paying accounts',
        description: 'Accounts on a paid plan today. The SQL has no date filter.',
        query: {
            kind: 'DataVisualizationNode',
            display: 'BoldNumber',
            source: { kind: 'HogQLQuery', query: "select count() from groups where properties.plan != 'free'" },
        },
        sql: { types: [['count()', 'UInt64']], rows: () => [[312]] },
    },
    {
        id: 9106,
        shortId: DEMO_INSIGHT_CHECKOUT,
        name: 'Checkout funnel',
        description: 'From the pricing page to a paid plan.',
        query: {
            kind: 'InsightVizNode',
            source: {
                kind: 'FunnelsQuery',
                series: [
                    { kind: 'EventsNode', event: 'viewed pricing' },
                    { kind: 'EventsNode', event: 'started checkout' },
                    { kind: 'EventsNode', event: 'paid' },
                ],
                dateRange: { date_from: '-30d', date_to: null },
            },
        },
        funnel: [
            { name: 'Viewed pricing', count: 4210, medianSeconds: null },
            { name: 'Started checkout', count: 1600, medianSeconds: 380 },
            { name: 'Entered payment', count: 928, medianSeconds: 145 },
            { name: 'Paid', count: 590, medianSeconds: 52 },
        ],
    },
    {
        id: 9109,
        shortId: DEMO_INSIGHT_RETENTION,
        name: 'Weekly retention',
        description: 'People who signed up, then viewed a page in the weeks after.',
        query: {
            kind: 'InsightVizNode',
            source: {
                kind: 'RetentionQuery',
                retentionFilter: {
                    period: 'Week',
                    totalIntervals: 8,
                    targetEntity: { id: 'user signed up', name: 'user signed up', type: 'events' },
                    returningEntity: { id: '$pageview', name: '$pageview', type: 'events' },
                },
                dateRange: { date_from: '-56d', date_to: null },
            },
        },
        retention: { cohortSize: 430, curve: [100, 46, 34, 29, 26, 24, 23, 22] },
    },
    {
        id: 9111,
        shortId: DEMO_INSIGHT_SQL_PAGES,
        name: 'Top pages this week',
        description: 'The most viewed pages in the last seven days. The SQL has its own date filter.',
        query: sqlQuery(
            "select properties.$pathname as page, count() as views, count(distinct person_id) as visitors from events where event = '$pageview' and timestamp > now() - interval 7 day group by page order by views desc limit 8",
            {
                display: 'ActionsTable',
                tableSettings: {
                    columns: [
                        { column: 'views', settings: { formatting: { style: 'number', decimalPlaces: 0 } } },
                        { column: 'visitors', settings: { formatting: { style: 'number', decimalPlaces: 0 } } },
                    ],
                },
            }
        ),
        sql: {
            types: [
                ['page', 'String'],
                ['views', 'UInt64'],
                ['visitors', 'UInt64'],
            ],
            rows: () => DEMO_SQL_PAGES,
        },
    },
    {
        id: 9112,
        shortId: DEMO_INSIGHT_SQL_SIGNUPS,
        name: 'Signups vs activations by day',
        description: 'New accounts per day, and the ones that created a dashboard.',
        query: sqlQuery(
            "select toDate(timestamp) as day, countIf(event = 'user signed up') as signups, countIf(event = 'dashboard created') as activations from events where {filters} group by day order by day",
            { display: 'ActionsLineGraph' },
            '-14d'
        ),
        sql: {
            types: [
                ['day', 'Date'],
                ['signups', 'UInt64'],
                ['activations', 'UInt64'],
            ],
            rows: (window, anchor) => {
                const today = startOfDay(anchor)
                return windowDays(window).map((day) => {
                    const daysBack = Math.round((today.getTime() - day.getTime()) / DAY)
                    const signups = signupsPerDay(daysBack, day.getDay())
                    return [isoDay(day), signups, Math.round(signups * (0.32 + noise(daysBack, 13) * 0.12))]
                })
            },
        },
    },
    {
        id: 9114,
        shortId: DEMO_INSIGHT_SQL_COUNTRIES,
        name: 'Signups by country',
        description: 'Signups, activation and time to activate per country.',
        query: sqlQuery(
            "select properties.$geoip_country_name as country, count() as signups, countIf(person.properties.activated) as activated, activated / signups as conversion, toUInt64(median(properties.seconds_to_activate)) as median_seconds, min(toDate(timestamp)) as first_seen from events where event = 'user signed up' group by country order by signups desc limit 8",
            {
                display: 'ActionsTable',
                tableSettings: {
                    columns: [
                        { column: 'signups', settings: { formatting: { style: 'number', decimalPlaces: 0 } } },
                        { column: 'activated', settings: { formatting: { style: 'number', decimalPlaces: 0 } } },
                        { column: 'conversion', settings: { formatting: { style: 'percent', decimalPlaces: 1 } } },
                        { column: 'median_seconds', settings: { formatting: { suffix: ' s' } } },
                    ],
                },
            }
        ),
        sql: {
            types: [
                ['country', 'String'],
                ['signups', 'UInt64'],
                ['activated', 'UInt64'],
                ['conversion', 'Float64'],
                ['median_seconds', 'UInt64'],
                ['first_seen', 'Date'],
            ],
            rows: () => DEMO_SQL_COUNTRIES,
        },
    },
    {
        id: 9113,
        shortId: DEMO_INSIGHT_SQL_REVENUE,
        name: 'Revenue by plan',
        description: 'Monthly recurring revenue per plan.',
        query: sqlQuery(
            'select properties.plan as plan, sum(properties.mrr) as mrr from groups group by plan order by mrr desc',
            {
                display: 'ActionsBarValue',
                chartSettings: {
                    xAxis: { column: 'plan' },
                    yAxis: [
                        {
                            column: 'mrr',
                            settings: { formatting: { prefix: '$', style: 'number', decimalPlaces: 0 } },
                        },
                    ],
                },
            }
        ),
        sql: {
            types: [
                ['plan', 'String'],
                ['mrr', 'Float64'],
            ],
            rows: () => [
                ['Enterprise', 48_000],
                ['Scale', 24_000],
                ['Teams', 12_000],
                ['Starter', 3000],
            ],
        },
    },
    {
        id: 9110,
        shortId: DEMO_INSIGHT_BROWSERS,
        name: 'Pageviews by browser',
        description: 'Page views in the window, per browser.',
        query: {
            kind: 'InsightVizNode',
            source: {
                kind: 'TrendsQuery',
                interval: 'day',
                series: [{ kind: 'EventsNode', event: '$pageview', name: '$pageview' }],
                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                trendsFilter: { display: 'ActionsBarValue' },
                dateRange: { date_from: '-14d', date_to: null },
            },
        },
        perDay: daily(9600, 4),
        breakdown: [
            { value: 'Chrome', share: 0.47 },
            { value: 'Safari', share: 0.26 },
            { value: 'Firefox', share: 0.1 },
            { value: 'Edge', share: 0.07 },
            { value: 'Samsung Internet', share: 0.04 },
            { value: '$$_posthog_breakdown_other_$$', share: 0.06 },
        ],
    },
    {
        id: 9107,
        shortId: 'demo-ins-activation',
        name: 'Activation rate',
        description: 'Share of new accounts that created a dashboard in their first week.',
        query: trendsQuery({
            event: 'dashboard created',
            display: 'ActionsLineGraph',
            dateFrom: '-30d',
            axisFormat: 'percentage',
        }),
        perDay: (daysBack, weekday) => Math.round(daily(240, 7, 0.2)(daysBack, weekday) / 10) / 10 + 2,
    },
    {
        id: 9108,
        shortId: 'demo-ins-tickets',
        name: 'New support tickets',
        description: 'Tickets opened per day.',
        query: trendsQuery({ event: 'ticket created', display: 'ActionsBar', dateFrom: '-14d' }),
        perDay: daily(42, 8, 0.3),
    },
]

interface DemoTileDef {
    id: number
    insight?: string
    text?: string
    overrides?: JsonRecord
}

interface DemoDashboardDef {
    id: number
    ref: string
    name: string
    description: string
    dateFrom: string | null
    tiles: DemoTileDef[]
}

const DEMO_DASHBOARDS: DemoDashboardDef[] = [
    {
        id: 9001,
        ref: DEMO_DASHBOARD_KPIS,
        name: 'Product KPIs',
        description: 'The numbers for the weekly product review.',
        dateFrom: '-14d',
        tiles: [
            { id: 1, insight: DEMO_INSIGHT_DAU },
            { id: 2, insight: 'demo-ins-pageviews' },
            { id: 3, insight: 'demo-ins-wau' },
            { id: 4, insight: DEMO_INSIGHT_SIGNUPS },
            { id: 5, insight: 'demo-ins-paying' },
            { id: 7, insight: DEMO_INSIGHT_BROWSERS },
            { id: 8, insight: DEMO_INSIGHT_CHECKOUT },
            { id: 9, insight: DEMO_INSIGHT_RETENTION },
            { id: 6, text: 'Review these on Monday. Revenue numbers live on the Growth dashboard.' },
        ],
    },
    {
        id: 9002,
        ref: DEMO_DASHBOARD_GROWTH,
        name: 'Growth',
        description: 'Activation and conversion.',
        dateFrom: '-30d',
        tiles: [
            { id: 1, insight: 'demo-ins-activation' },
            { id: 2, insight: DEMO_INSIGHT_SIGNUPS },
            { id: 3, insight: DEMO_INSIGHT_CHECKOUT },
            { id: 4, insight: DEMO_INSIGHT_SQL_PAGES },
        ],
    },
    {
        id: 9005,
        ref: DEMO_DASHBOARD_SQL,
        name: 'SQL views',
        description: 'Tables and charts written in SQL.',
        dateFrom: '-14d',
        tiles: [
            { id: 1, insight: DEMO_INSIGHT_SQL_PAGES },
            { id: 2, insight: DEMO_INSIGHT_SQL_SIGNUPS },
            { id: 3, insight: DEMO_INSIGHT_SQL_REVENUE },
            { id: 4, insight: 'demo-ins-paying' },
            { id: 5, insight: DEMO_INSIGHT_SQL_COUNTRIES },
        ],
    },
    {
        id: 9003,
        ref: 'demo-dash-marketing',
        name: 'Marketing site',
        description: 'Traffic to the public site.',
        dateFrom: '-7d',
        tiles: [
            { id: 1, insight: 'demo-ins-pageviews' },
            { id: 2, insight: DEMO_INSIGHT_DAU, overrides: { date_from: '-30d' } },
        ],
    },
    {
        id: 9004,
        ref: 'demo-dash-support',
        name: 'Support',
        description: 'Ticket volume.',
        dateFrom: '-14d',
        tiles: [
            { id: 1, insight: 'demo-ins-tickets' },
            { id: 2, text: 'Weekend tickets wait until Monday.' },
        ],
    },
]

function insightDef(shortId: string): DemoInsightDef | undefined {
    return DEMO_INSIGHTS.find((insight) => insight.shortId === shortId || `#${insight.id}` === shortId)
}

function dashboardDef(ref: string): DemoDashboardDef | undefined {
    return DEMO_DASHBOARDS.find((dashboard) => dashboard.ref === ref)
}

function startOfDay(date: Date): Date {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function addDays(date: Date, days: number): Date {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days)
}

function isoDay(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function offsetSuffix(date: Date): string {
    const minutes = -date.getTimezoneOffset()
    const sign = minutes >= 0 ? '+' : '-'
    const absolute = Math.abs(minutes)
    return `${sign}${String(Math.floor(absolute / 60)).padStart(2, '0')}:${String(absolute % 60).padStart(2, '0')}`
}

function parseDay(value: string): Date | null {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
    return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null
}

interface DemoWindow {
    start: Date
    end: Date
}

/** The days a range covers in the demo, like the server resolves them: "Last 7 days" is 8 days ending today. */
function demoWindow(dateFrom: string | null, dateTo: string | null, anchor: Date): DemoWindow {
    const today = startOfDay(anchor)
    const weekStart = addDays(today, -((today.getDay() + 6) % 7))
    const window = ((): DemoWindow => {
        if (!dateFrom) {
            return { start: addDays(today, -7), end: today }
        }
        const days = /^-(\d+)d$/.exec(dateFrom)
        if (days) {
            return { start: addDays(today, -Number(days[1])), end: today }
        }
        const hours = /^-(\d+)h$/.exec(dateFrom)
        if (hours) {
            return { start: addDays(today, -Math.ceil(Number(hours[1]) / 24)), end: today }
        }
        switch (dateFrom) {
            case 'dStart':
                return { start: today, end: today }
            case '-1dStart':
                return { start: addDays(today, -1), end: addDays(today, -1) }
            case 'wStart':
                return { start: weekStart, end: today }
            case '-1wStart':
                return { start: addDays(weekStart, -7), end: addDays(weekStart, -1) }
            case 'mStart':
                return { start: new Date(today.getFullYear(), today.getMonth(), 1), end: today }
            case '-1mStart':
                return {
                    start: new Date(today.getFullYear(), today.getMonth() - 1, 1),
                    end: new Date(today.getFullYear(), today.getMonth(), 0),
                }
            case 'yStart':
                return { start: new Date(today.getFullYear(), 0, 1), end: today }
            case 'all':
                return { start: addDays(today, -180), end: today }
        }
        const start = parseDay(dateFrom) ?? addDays(today, -7)
        const end = (dateTo ? parseDay(dateTo) : null) ?? today
        return { start, end }
    })()
    const end = window.end > today ? today : window.end
    return { start: window.start > end ? end : window.start, end }
}

function windowDays(window: DemoWindow): Date[] {
    const days: Date[] = []
    for (let day = window.start; day <= window.end; day = addDays(day, 1)) {
        days.push(day)
    }
    return days
}

function trendsEntry(
    def: DemoInsightDef,
    window: DemoWindow,
    anchor: Date,
    compareLabel: 'current' | 'previous' | null
): JsonRecord {
    const today = startOfDay(anchor)
    const days = windowDays(window)
    const math = ((def.query.source as JsonRecord).series as JsonRecord[])[0]?.math
    const base = {
        action: { order: 0, math: math ?? 'total' },
        label: def.name,
        ...(compareLabel ? { compare: true, compare_label: compareLabel } : {}),
    }
    if (def.aggregate) {
        return { ...base, aggregated_value: def.aggregate(days.length) }
    }
    // Today has data only up to the anchor time, so its bucket is in progress.
    const todayShare = Math.max(0.15, (anchor.getTime() - today.getTime()) / DAY)
    const data = days.map((day) => {
        const daysBack = Math.round((today.getTime() - day.getTime()) / DAY)
        const value = def.perDay?.(daysBack, day.getDay()) ?? 0
        return daysBack === 0 ? Math.round(value * todayShare * 10) / 10 : value
    })
    return {
        ...base,
        days: days.map(isoDay),
        labels: days.map(isoDay),
        data,
        count: data.reduce((total, value) => total + value, 0),
    }
}

function previousWindow(window: DemoWindow): DemoWindow {
    const length = windowDays(window).length
    return { start: addDays(window.start, -length), end: addDays(window.end, -length) }
}

function funnelResult(def: DemoInsightDef, window: DemoWindow): JsonRecord[] {
    const scale = windowDays(window).length / 31
    return (def.funnel ?? []).map((step, order) => ({
        action_id: step.name,
        name: step.name,
        custom_name: null,
        order,
        type: 'events',
        people: [],
        count: Math.max(1, Math.round(step.count * scale)),
        average_conversion_time: step.medianSeconds === null ? null : Math.round(step.medianSeconds * 1.6),
        median_conversion_time: step.medianSeconds,
    }))
}

/** Like the server: every cohort answers all eight weeks, and weeks that have not started yet count 0. */
function retentionResult(def: DemoInsightDef, window: DemoWindow, anchor: Date): JsonRecord[] {
    const retention = def.retention
    if (!retention) {
        return []
    }
    const weeks = retention.curve.length
    const today = startOfDay(anchor)
    const lastStart = addDays(window.end, -window.end.getDay())
    return Array.from({ length: weeks }, (_, cohort) => {
        const start = addDays(lastStart, (cohort - weeks + 1) * 7)
        const size = Math.round(retention.cohortSize * (0.9 + noise(cohort, 11) * 0.2))
        const values = retention.curve.map((percent, week) => {
            const started = addDays(start, week * 7) <= today
            const jitter = week === 0 ? 1 : 0.92 + noise(cohort * 8 + week, 12) * 0.16
            return { count: started ? Math.round(size * (percent / 100) * jitter) : 0, label: `Week ${week}` }
        })
        return {
            date: `${isoDay(start)}T00:00:00${offsetSuffix(start)}`,
            label: `Week ${cohort}`,
            values,
            breakdown_value: null,
        }
    })
}

function retentionWindow(def: DemoInsightDef, window: DemoWindow): DemoWindow {
    const weeks = def.retention?.curve.length ?? 1
    const lastStart = addDays(window.end, -window.end.getDay())
    return { start: addDays(lastStart, -(weeks - 1) * 7), end: window.end }
}

function breakdownResult(def: DemoInsightDef, window: DemoWindow, anchor: Date): JsonRecord[] {
    const total = (trendsEntry(def, window, anchor, null).count as number | undefined) ?? 0
    return (def.breakdown ?? []).map((item) => ({
        action: { order: 0, math: 'total' },
        label: item.value,
        breakdown_value: item.value,
        aggregated_value: Math.round(total * item.share),
        count: 0,
        data: [],
        days: [],
    }))
}

function demoResult(def: DemoInsightDef, window: DemoWindow, anchor: Date, compare: boolean): unknown {
    if (def.sql) {
        return def.sql.rows(window, anchor)
    }
    if (def.funnel) {
        return funnelResult(def, window)
    }
    if (def.retention) {
        return retentionResult(def, window, anchor)
    }
    if (def.breakdown) {
        return breakdownResult(def, window, anchor)
    }
    if (!compare) {
        return [trendsEntry(def, window, anchor, null)]
    }
    return [trendsEntry(def, window, anchor, 'current'), trendsEntry(def, previousWindow(window), anchor, 'previous')]
}

interface DemoFreshness {
    last_refresh: string
    cache_target_age: string
    next_allowed_client_refresh: string
    is_cached: boolean
}

/** Before a demo refresh the numbers are 42 minutes old and may be forced; after one, the next force waits 3 minutes. */
function demoFreshness(anchor: number, refreshedAt: number | undefined): DemoFreshness {
    const lastRefresh = refreshedAt ?? anchor - DEMO_DATA_AGE_MS
    const window = refreshedAt ? 3 * MINUTE : 15 * MINUTE
    return {
        last_refresh: new Date(lastRefresh).toISOString(),
        cache_target_age: new Date(lastRefresh + 6 * HOUR).toISOString(),
        next_allowed_client_refresh: new Date(lastRefresh + window).toISOString(),
        is_cached: refreshedAt === undefined || Date.now() - refreshedAt > DEMO_READ_MS * 4,
    }
}

function resolvedRange(window: DemoWindow): { date_from: string; date_to: string } {
    const suffix = offsetSuffix(window.end)
    return {
        date_from: `${isoDay(window.start)}T00:00:00${suffix}`,
        date_to: `${isoDay(window.end)}T23:59:59${suffix}`,
    }
}

function sourceOf(query: JsonRecord): JsonRecord {
    return (query.source as JsonRecord | undefined) ?? query
}

function savedDateRange(query: JsonRecord): JsonRecord | undefined {
    const source = sourceOf(query)
    return (source.dateRange ?? (source.filters as JsonRecord | undefined)?.dateRange) as JsonRecord | undefined
}

function withRange(query: JsonRecord, dateFrom: string | null, dateTo: string | null): JsonRecord {
    const source = sourceOf(query)
    const dateRange = { date_from: dateFrom, date_to: dateTo }
    // Only a SQL insight with `{filters}` takes the dashboard range; the server runs any other SQL as written.
    if (source.kind === 'HogQLQuery' && typeof source.query === 'string' && source.query.includes('{filters}')) {
        return { ...query, source: { ...source, filters: { ...(source.filters as JsonRecord), dateRange } } }
    }
    if (query.kind !== 'InsightVizNode') {
        return query
    }
    return { ...query, source: { ...source, dateRange } }
}

/** The fields the server adds to a SQL insight's response. */
function sqlFields(def: DemoInsightDef): Pick<InsightApi, 'columns' | 'types' | 'hasMore'> {
    if (!def.sql) {
        return {}
    }
    return { columns: def.sql.types.map(([column]) => column), types: def.sql.types, hasMore: false }
}

export interface DemoInsightRequest {
    shortId: string
    dashboardRef: string | null
    override: JsonRecord | null
    /** The tile's own filters, which win over the dashboard and the override. */
    tileOverrides?: JsonRecord | null
    /** Device ms of this item's last forced demo read. */
    refreshedAt?: number
}

const DEMO_AUTHOR = { first_name: 'Sam', last_name: 'Rivera', email: 'sam@example.com' }

/** A demo `GET insights/{id}/` answer, or undefined for an id the demo does not have (a 404). */
export function demoInsightResponse(request: DemoInsightRequest, anchor: number): InsightApi | undefined {
    const def = insightDef(request.shortId)
    if (!def) {
        return undefined
    }
    const dashboard = request.dashboardRef ? dashboardDef(request.dashboardRef) : undefined
    // The server's layers: the tile's own dates win, then the request override, then the dashboard, then the insight.
    const layer: JsonRecord = request.tileOverrides?.date_from
        ? request.tileOverrides
        : request.override?.date_from
          ? request.override
          : dashboard?.dateFrom
            ? { date_from: dashboard.dateFrom, date_to: null }
            : (savedDateRange(def.query) ?? {})
    const dateFrom = typeof layer.date_from === 'string' ? layer.date_from : null
    const dateTo = typeof layer.date_to === 'string' ? layer.date_to : null
    const requested = demoWindow(dateFrom, dateTo, new Date(anchor))
    // Retention shows a fixed number of cohorts that end in the requested window, so its range starts earlier.
    const window = def.retention ? retentionWindow(def, requested) : requested
    return {
        id: def.id,
        short_id: def.shortId,
        name: def.name,
        derived_name: null,
        description: def.description,
        query: withRange(def.query, dateFrom, dateTo),
        result: demoResult(def, window, new Date(anchor), false),
        ...sqlFields(def),
        ...demoFreshness(anchor, request.refreshedAt),
        timezone: 'UTC',
        resolved_date_range: resolvedRange(window),
        created_by: DEMO_AUTHOR,
        created_at: '2026-03-03T10:00:00Z',
    }
}

/** A demo `POST query/` answer for "Compare to previous period" on an insight. */
export function demoCompareResponse(
    query: JsonRecord,
    shortId: string,
    anchor: number,
    refreshedAt?: number
): JsonRecord {
    const def = insightDef(shortId)
    const range = (query.dateRange as JsonRecord | undefined) ?? {}
    const window = demoWindow(
        (range.date_from as string | null) ?? null,
        (range.date_to as string | null) ?? null,
        new Date(anchor)
    )
    return {
        results: def ? demoResult(def, window, new Date(anchor), asRecord(query.compareFilter)?.compare === true) : [],
        ...demoFreshness(anchor, refreshedAt),
        timezone: 'UTC',
        resolved_date_range: resolvedRange(window),
    }
}

/** A demo `GET dashboards/{id}/?refresh=force_cache` answer, or undefined for a dashboard the demo does not have. */
export function demoDashboardResponse(
    ref: string,
    override: JsonRecord | null,
    anchor: number,
    refreshedAt: (shortId: string) => number | undefined
): DashboardApi | undefined {
    const def = dashboardDef(ref)
    if (!def) {
        return undefined
    }
    const tiles = def.tiles.map((tile, index): DashboardTileApi => {
        const layouts = { sm: { x: 0, y: index * 4, w: 12, h: 4 } }
        if (!tile.insight) {
            return { id: tile.id, insight: null, text: { body: tile.text ?? '' }, layouts }
        }
        const insight = demoInsightResponse(
            {
                shortId: tile.insight,
                dashboardRef: ref,
                override,
                tileOverrides: tile.overrides ?? null,
                refreshedAt: refreshedAt(tile.insight),
            },
            anchor
        )
        return { id: tile.id, insight: insight ?? null, layouts, filters_overrides: tile.overrides ?? null }
    })
    return {
        id: def.id,
        name: def.name,
        description: def.description,
        filters: def.dateFrom ? { date_from: def.dateFrom, date_to: null } : {},
        last_refresh: new Date(anchor - DEMO_DATA_AGE_MS).toISOString(),
        tiles,
    }
}

export function demoDashboardRows(): DashboardBasicApi[] {
    return DEMO_DASHBOARDS.map((dashboard) => ({
        id: dashboard.id,
        name: dashboard.name,
        description: dashboard.description,
        last_viewed_at: null,
    }))
}

/** Demo dashboards are opened by `ref`, so Browse rows carry the ref instead of the numeric id. */
export function demoDashboardRefFor(id: number): string | undefined {
    return DEMO_DASHBOARDS.find((dashboard) => dashboard.id === id)?.ref
}

export function demoInsightRows(): InsightBasicApi[] {
    return DEMO_INSIGHTS.map((insight) => ({
        id: insight.id,
        short_id: insight.shortId,
        name: insight.name,
        derived_name: null,
        description: insight.description,
        last_modified_at: null,
    }))
}

const WEB_METRICS: { key: string; kind: string; perWeek: number; previous: number; isIncreaseBad?: boolean }[] = [
    { key: 'visitors', kind: 'unit', perWeek: 8412, previous: 7930 },
    { key: 'views', kind: 'unit', perWeek: 31_207, previous: 30_118 },
    { key: 'sessions', kind: 'unit', perWeek: 10_906, previous: 10_450 },
    { key: 'session duration', kind: 'duration_s', perWeek: 194, previous: 188 },
    { key: 'bounce rate', kind: 'percentage', perWeek: 41.6, previous: 43.2, isIncreaseBad: true },
]

/** A demo web analytics overview for the query's range. Counts scale with the window; durations and rates do not. */
export function demoWebOverviewResponse(
    query: JsonRecord,
    anchor: number,
    refreshedAt?: number
): WebOverviewResponseApi {
    const range = (query.dateRange as JsonRecord | undefined) ?? {}
    const window = demoWindow(
        (range.date_from as string | null) ?? null,
        (range.date_to as string | null) ?? null,
        new Date(anchor)
    )
    const scale = windowDays(window).length / 8
    return {
        results: WEB_METRICS.map((metric) => {
            const counts = metric.kind === 'unit'
            const value = counts ? Math.round(metric.perWeek * scale) : metric.perWeek
            const previous = counts ? Math.round(metric.previous * scale) : metric.previous
            return {
                key: metric.key,
                kind: metric.kind,
                value,
                previous,
                changeFromPreviousPct: Math.round(((value - previous) / previous) * 1000) / 10,
                isIncreaseBad: metric.isIncreaseBad ?? false,
            }
        }),
        ...demoFreshness(anchor, refreshedAt),
        timezone: 'UTC',
        resolved_date_range: resolvedRange(window),
    }
}

const DEMO_ACTORS: { id: string; email: string; recordings: string[] }[] = [
    { id: 'demo-person-1', email: 'avery@example.com', recordings: ['demo-recording-1'] },
    { id: 'demo-person-2', email: 'blake@example.com', recordings: ['demo-recording-2', 'demo-recording-3'] },
    { id: 'demo-person-3', email: 'casey@example.com', recordings: [] },
    { id: 'demo-person-4', email: 'devon@example.com', recordings: [] },
    { id: 'demo-person-5', email: 'emery@example.com', recordings: [] },
]

/** Five people at any point, two of them with recordings. */
export function demoActorsResponse(input: Pick<ActorsAtPointInput, 'includeRecordings'>): ActorsResponseApi {
    return {
        results: DEMO_ACTORS.map((actor) => {
            const person = { id: actor.id, distinct_ids: [actor.id], properties: { email: actor.email } }
            return input.includeRecordings
                ? [person, actor.recordings.map((session_id) => ({ session_id, events: [] }))]
                : [person]
        }),
        hasMore: false,
    }
}

function shortcut(id: string, path: string, type: string, ref: string | null, href: string, order: number) {
    return { id, path, type, ref, href, order, created_at: '2026-01-05T09:00:00Z' } satisfies FileSystemShortcutApi
}

const DEFAULT_SHORTCUTS: FileSystemShortcutApi[] = [
    shortcut('demo-pin-kpis', 'Product KPIs', 'dashboard', DEMO_DASHBOARD_KPIS, `/dashboard/${DEMO_DASHBOARD_KPIS}`, 0),
    shortcut('demo-pin-signups', 'Signups', 'insight', DEMO_INSIGHT_SIGNUPS, `/insights/${DEMO_INSIGHT_SIGNUPS}`, 1),
    shortcut('demo-pin-web', 'Web analytics', 'web_analytics', null, '/web', 2),
    shortcut('demo-pin-notes', 'Launch notes', 'notebook', 'demo-nb-launch', '/notebooks/demo-nb-launch', 3),
]

const DEFAULT_DISPLAY: Record<string, PinDisplay> = {
    'demo-pin-kpis': { mode: 'number', tileId: 1, insightId: 9102, insightShortId: DEMO_INSIGHT_DAU },
    'demo-pin-signups': { mode: 'chart' },
}

function defaultRecent(now: number): DeviceRecentEntry[] {
    return [
        {
            kind: 'dashboard',
            ref: DEMO_DASHBOARD_GROWTH,
            name: 'Growth',
            viewedAt: new Date(now - 2 * HOUR).toISOString(),
        },
        {
            kind: 'insight',
            ref: DEMO_INSIGHT_CHECKOUT,
            name: 'Checkout funnel',
            viewedAt: new Date(now - 26 * HOUR).toISOString(),
        },
    ]
}

interface DemoViewsState {
    shortcuts: FileSystemShortcutApi[]
    display: Record<string, PinDisplay>
    rank: Record<string, number>
    recent: DeviceRecentEntry[]
    /** Device ms of each item's last forced demo read, keyed by the freshness key. */
    refreshedAt: Record<string, number>
    addShortcut: (input: ShortcutInput) => FileSystemShortcutApi
    removeShortcuts: (ids: readonly string[]) => void
    setDisplay: (shortcutId: string, display: PinDisplay) => void
    setOrder: (shortcutIds: readonly string[]) => void
    recordRecent: (entry: DeviceRecentEntry) => void
    markRefreshed: (key: string) => void
    reset: () => void
}

function freshDemoViews(): Pick<DemoViewsState, 'shortcuts' | 'display' | 'rank' | 'recent' | 'refreshedAt'> {
    return {
        shortcuts: DEFAULT_SHORTCUTS,
        display: DEFAULT_DISPLAY,
        rank: {},
        recent: defaultRecent(Date.now()),
        refreshedAt: {},
    }
}

let demoPinCounter = 0

/** The demo's pins, their arrangement and the phone's Recent, in memory. They reset when demo mode turns on or off. */
export const useDemoViews = create<DemoViewsState>()((set) => ({
    ...freshDemoViews(),
    addShortcut: (input) => {
        demoPinCounter += 1
        // A pin from a dashboard screen names the dashboard by id, but demo dashboards open by ref.
        const ref =
            input.type === 'dashboard' && input.ref ? (demoDashboardRefFor(Number(input.ref)) ?? input.ref) : input.ref
        const row: FileSystemShortcutApi = {
            ...input,
            ref,
            href: ref === input.ref ? input.href : `/dashboard/${ref}`,
            id: `demo-pin-added-${demoPinCounter}`,
            order: DEFAULT_SHORTCUTS.length + demoPinCounter,
            created_at: new Date().toISOString(),
        }
        set((state) => ({ shortcuts: [...state.shortcuts, row] }))
        return row
    },
    removeShortcuts: (ids) => set((state) => ({ shortcuts: state.shortcuts.filter((row) => !ids.includes(row.id)) })),
    setDisplay: (shortcutId, display) => set((state) => ({ display: { ...state.display, [shortcutId]: display } })),
    setOrder: (shortcutIds) => set({ rank: Object.fromEntries(shortcutIds.map((id, index) => [id, index])) }),
    recordRecent: (entry) =>
        set((state) => ({
            recent: [entry, ...state.recent.filter((item) => item.kind !== entry.kind || item.ref !== entry.ref)].slice(
                0,
                20
            ),
        })),
    markRefreshed: (key) => set((state) => ({ refreshedAt: { ...state.refreshedAt, [key]: Date.now() } })),
    reset: () => set(freshDemoViews()),
}))

useDemoMode.subscribe((state, previous) => {
    if (state.enabled !== previous.enabled) {
        useDemoViews.getState().reset()
    }
})

/** The demo's time anchor, so every Views fixture lines up with the inbox fixtures. */
export function demoAnchor(): number {
    return useDemoMode.getState().anchor
}
