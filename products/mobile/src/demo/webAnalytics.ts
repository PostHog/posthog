import type { WebOverviewResponseApi, WebQueryResponseApi } from '@/api/webAnalytics'
import { asRecord, isRecord } from '@/lib/records'
import { breakdownFilter } from '@/model/adapters/webAnalyticsBreakdowns'
import type { WebBreakdown, WebPropertyFilter, WebTrendMetric } from '@/model/views'

import {
    addDays,
    DAY,
    type DemoWindow,
    demoFreshness,
    demoWindow,
    HOUR,
    isoDay,
    noise,
    offsetSuffix,
    resolvedRange,
    startOfDay,
    windowDays,
} from './views'

// Web analytics demo answers for hedgebox.net, the demo's invented file-sharing site. Every path, domain and number is
// invented. The answers have the server's shapes, so demo mode runs the same adapters as live mode. Counts scale with
// the window, and a filter scales them by the share of the value it filters, so the numbers stay consistent: the
// overview with "Path: /pricing" shows the visitors of the /pricing row.

type JsonRecord = Record<string, unknown>

/** Visitors in an 8-day window ("Last 7 days" resolves to 8 days), the overview's base. */
const VISITORS_PER_8_DAYS = 8412

const OVERVIEW: { key: string; kind: string; value: number; previous: number; isIncreaseBad?: boolean }[] = [
    { key: 'visitors', kind: 'unit', value: VISITORS_PER_8_DAYS, previous: 7930 },
    { key: 'views', kind: 'unit', value: 31_207, previous: 30_118 },
    { key: 'sessions', kind: 'unit', value: 10_906, previous: 10_450 },
    { key: 'session duration', kind: 'duration_s', value: 194, previous: 188 },
    { key: 'bounce rate', kind: 'percentage', value: 41.6, previous: 43.2, isIncreaseBad: true },
]

/** `[value, share of visitors, views or clicks per visitor]`. Page shares add up to more than 1: people see many pages. */
type DemoRow = [value: unknown, share: number, perVisitor?: number]

const TABLES: Record<WebBreakdown, DemoRow[]> = {
    Page: [
        ['/', 0.42, 1.6],
        ['/pricing', 0.16, 1.1],
        ['/files', 0.15, 3.3],
        ['/signup', 0.115, 1.3],
        ['/login', 0.11, 1.5],
        ['/features', 0.083, 1.7],
        ['/blog', 0.065, 1.3],
        ['/docs', 0.058, 2],
        ['/blog/secure-file-sharing-for-teams', 0.05, 1.4],
        ['/download/mac', 0.045, 1.3],
        ['/account/billing', 0.037, 1.4],
        ['/integrations/slack', 0.032, 1.2],
        ['/download/windows', 0.03, 1.3],
        ['/about', 0.026, 1.1],
        ['/careers', 0.021, 1.6],
        ['/changelog', 0.019, 1.2],
        ['/security', 0.017, 1.1],
        ['/blog/shared-folders', 0.015, 1.2],
        ['/contact', 0.013, 1.1],
        ['/terms', 0.009, 1],
        ['/privacy', 0.008, 1],
        ['/status', 0.007, 1.4],
    ],
    InitialPage: [
        ['/', 0.48, 3.4],
        ['/pricing', 0.12, 2.6],
        ['/blog/secure-file-sharing-for-teams', 0.09, 2.1],
        ['/login', 0.08, 4.2],
        ['/features', 0.06, 2.9],
        ['/docs', 0.05, 3.1],
        ['/signup', 0.04, 2.5],
        ['/download/mac', 0.03, 1.8],
        ['/blog/shared-folders', 0.02, 2],
        ['/integrations/slack', 0.015, 2.2],
        ['/careers', 0.01, 1.9],
    ],
    ExitPage: [
        ['/files', 0.24, 3.8],
        ['/', 0.21, 2.4],
        ['/pricing', 0.12, 3.1],
        ['/download/mac', 0.08, 3.5],
        ['/login', 0.07, 2.2],
        ['/account/billing', 0.05, 4.4],
        ['/docs', 0.05, 3.6],
        ['/signup', 0.04, 3.3],
        ['/blog', 0.03, 2.7],
        ['/download/windows', 0.03, 3.2],
        ['/contact', 0.015, 2.9],
    ],
    ExitClick: [
        ['https://community.hedgebox.net/', 0.031, 1.4],
        ['https://status.hedgebox.net/', 0.019, 1.2],
        ['https://example.com/partners/hedgebox', 0.012, 1.1],
        ['https://help.hedgebox.net/articles/sharing-links', 0.009, 1.3],
        ['https://example.org/reviews/file-sharing', 0.006, 1],
        ['https://events.example.com/hedgebox-meetup', 0.004, 1],
    ],
    InitialChannelType: [
        ['Direct', 0.38, 3.1],
        ['Organic Search', 0.31, 4.3],
        ['Referral', 0.16, 4.1],
        ['Organic Social', 0.08, 3.8],
        ['Paid Search', 0.06, 4.6],
        ['Email', 0.03, 3.3],
        ['Organic Video', 0.012, 2.9],
        ['Paid Social', 0.008, 2.5],
    ],
    InitialReferringDomain: [
        ['$direct', 0.38, 3.1],
        ['www.google.com', 0.27, 4.3],
        ['duckduckgo.com', 0.04, 4.1],
        ['news.example.com', 0.07, 3.6],
        ['www.bing.com', 0.03, 4],
        ['blog.example.org', 0.025, 3.2],
        ['forum.example.net', 0.02, 3.9],
        ['mail.example.com', 0.015, 3],
    ],
    InitialUTMSource: [
        [null, 0.83, 3.4],
        ['newsletter', 0.06, 3.3],
        ['google', 0.05, 4.6],
        ['partner-site', 0.03, 3.9],
        ['social', 0.02, 2.8],
    ],
    InitialUTMMedium: [
        [null, 0.83, 3.4],
        ['email', 0.06, 3.3],
        ['cpc', 0.05, 4.6],
        ['referral', 0.03, 3.9],
        ['social', 0.02, 2.8],
    ],
    InitialUTMCampaign: [
        [null, 0.83, 3.4],
        ['fall-launch', 0.07, 3.5],
        ['team-plan', 0.05, 4.2],
        ['webinar-october', 0.03, 3],
        ['shared-folders', 0.015, 3.1],
    ],
    DeviceType: [
        ['Desktop', 0.62, 4.1],
        ['Mobile', 0.34, 2.6],
        ['Tablet', 0.04, 3],
    ],
    Browser: [
        ['Chrome', 0.48, 3.9],
        ['Safari', 0.19, 3.2],
        ['Mobile Safari', 0.14, 2.5],
        ['Firefox', 0.07, 4.2],
        ['Edge', 0.06, 3.8],
        ['Chrome iOS', 0.03, 2.4],
        ['Samsung Internet', 0.02, 2.2],
    ],
    OS: [
        ['Mac OS X', 0.36, 4],
        ['Windows', 0.25, 4.1],
        ['iOS', 0.19, 2.5],
        ['Android', 0.14, 2.6],
        ['Linux', 0.04, 4.4],
        ['Chrome OS', 0.015, 3.5],
    ],
    Viewport: [
        [[1440, 900], 0.17, 4],
        [[1920, 1080], 0.15, 4.2],
        [[390, 844], 0.12, 2.6],
        [[1536, 864], 0.09, 3.9],
        [[430, 932], 0.08, 2.5],
        [[1280, 720], 0.06, 3.7],
        [[375, 812], 0.05, 2.4],
        [[2560, 1440], 0.04, 4.5],
        [[820, 1180], 0.03, 3],
    ],
    Country: [
        ['US', 0.41, 3.6],
        ['GB', 0.11, 3.4],
        ['DE', 0.09, 3.8],
        ['IN', 0.08, 3.1],
        ['CA', 0.06, 3.5],
        ['FR', 0.05, 3.6],
        ['NL', 0.04, 3.9],
        ['AU', 0.03, 3.3],
        ['BR', 0.03, 3],
        ['ES', 0.02, 3.4],
        [null, 0.01, 2.8],
    ],
    Region: [
        [['US', 'CA', 'California'], 0.13, 3.7],
        [['US', 'NY', 'New York'], 0.08, 3.5],
        [['GB', 'ENG', 'England'], 0.09, 3.4],
        [['DE', 'BE', 'Berlin'], 0.04, 3.9],
        [['US', 'TX', 'Texas'], 0.05, 3.5],
        [['IN', 'KA', 'Karnataka'], 0.04, 3.1],
        [['CA', 'ON', 'Ontario'], 0.035, 3.5],
        [['US', 'WA', 'Washington'], 0.03, 3.8],
        [['FR', 'IDF', 'Île-de-France'], 0.03, 3.6],
        [['NL', null, null], 0.01, 3.2],
    ],
    City: [
        [['US', 'San Francisco'], 0.06, 3.8],
        [['US', 'New York'], 0.055, 3.5],
        [['GB', 'London'], 0.06, 3.4],
        [['DE', 'Berlin'], 0.04, 3.9],
        [['IN', 'Bengaluru'], 0.035, 3.1],
        [['US', 'Austin'], 0.025, 3.6],
        [['CA', 'Toronto'], 0.025, 3.5],
        [['US', 'Seattle'], 0.02, 3.8],
        [['FR', 'Paris'], 0.025, 3.6],
        [['NL', 'Amsterdam'], 0.02, 3.9],
        [['US', null], 0.015, 3],
    ],
    Timezone: [
        [-5, 0.19, 3.6],
        [-8, 0.15, 3.7],
        [0, 0.11, 3.4],
        [1, 0.14, 3.7],
        [5.5, 0.08, 3.1],
        [-6, 0.06, 3.5],
        [-7, 0.04, 3.5],
        [10, 0.03, 3.3],
        [-3, 0.03, 3],
        [9, 0.02, 3.2],
    ],
    Language: [
        ['en-US', 0.57, 3.6],
        ['de-DE', 0.09, 3.8],
        ['fr-FR', 0.05, 3.6],
        ['es-ES', 0.04, 3.4],
        ['pt-BR', 0.03, 3],
        ['nl-NL', 0.03, 3.9],
        ['hi-IN', 0.02, 3],
        ['ja-JP', 0.02, 3.2],
        ['it-IT', 0.015, 3.5],
    ],
}

const BREAKDOWNS = Object.keys(TABLES) as WebBreakdown[]

function sameProperty(left: WebPropertyFilter, right: WebPropertyFilter): boolean {
    return left.key === right.key && left.operator === right.operator && (left.value ?? null) === (right.value ?? null)
}

function propertiesOf(value: unknown): WebPropertyFilter[] {
    return (Array.isArray(value) ? value : []).filter(isRecord).flatMap((entry): WebPropertyFilter[] => {
        const { key, type, operator, value: filterValue } = entry
        if (typeof key !== 'string' || (type !== 'event' && type !== 'session')) {
            return []
        }
        return [
            {
                key,
                type,
                operator: operator === 'is_not_set' || operator === 'regex' ? operator : 'exact',
                ...(typeof filterValue === 'string' || typeof filterValue === 'number' ? { value: filterValue } : {}),
            },
        ]
    })
}

function hash(text: string): number {
    let value = 0
    for (let index = 0; index < text.length; index++) {
        value = (value * 31 + text.charCodeAt(index)) % 100_003
    }
    return value
}

/**
 * How much the filters narrow the traffic: the product of the matched rows' shares. `skip` leaves out the filters of
 * the table being drawn, which instead keep only their own rows.
 */
function filterScale(properties: readonly WebPropertyFilter[], skip: ReadonlySet<string> = new Set()): number {
    let scale = 1
    const matched = new Set<string>()
    for (const breakdown of BREAKDOWNS) {
        for (const [value, share] of TABLES[breakdown]) {
            const filter = breakdownFilter(breakdown, value)
            if (
                !filter ||
                filter.properties.some((property) => skip.has(property.key) || matched.has(property.key)) ||
                !filter.properties.every((property) => properties.some((active) => sameProperty(active, property)))
            ) {
                continue
            }
            for (const property of filter.properties) {
                matched.add(property.key)
            }
            scale *= Math.min(1, share)
        }
    }
    for (const property of properties) {
        if (!matched.has(property.key) && !skip.has(property.key)) {
            scale *= 0.3
        }
    }
    return scale
}

function windowOf(query: JsonRecord, anchor: number): DemoWindow {
    const range = asRecord(query.dateRange) ?? {}
    return demoWindow(
        typeof range.date_from === 'string' ? range.date_from : null,
        typeof range.date_to === 'string' ? range.date_to : null,
        new Date(anchor)
    )
}

function freshness(
    window: DemoWindow,
    anchor: number,
    refreshedAt: number | undefined
): Omit<WebQueryResponseApi, 'results' | 'columns' | 'hasMore'> {
    return { ...demoFreshness(anchor, refreshedAt), timezone: 'UTC', resolved_date_range: resolvedRange(window) }
}

export function demoWebOverviewResponse(
    query: JsonRecord,
    anchor: number,
    refreshedAt?: number
): WebOverviewResponseApi {
    const window = windowOf(query, anchor)
    const properties = propertiesOf(query.properties)
    const scale = (windowDays(window).length / 8) * filterScale(properties)
    // A filter moves the rates a little, so a filtered overview does not repeat the unfiltered one.
    const shift = properties.length > 0 ? 0.9 + noise(hash(JSON.stringify(properties)), 3) * 0.2 : 1
    return {
        results: OVERVIEW.map((metric) => {
            const counts = metric.kind === 'unit'
            const value = counts ? Math.round(metric.value * scale) : Math.round(metric.value * shift * 10) / 10
            const previous = counts ? Math.round(metric.previous * scale) : metric.previous
            return {
                key: metric.key,
                kind: metric.kind,
                value,
                previous,
                changeFromPreviousPct: previous ? Math.round(((value - previous) / previous) * 1000) / 10 : null,
                isIncreaseBad: metric.isIncreaseBad ?? false,
            }
        }),
        ...freshness(window, anchor, refreshedAt),
    }
}

function tableResponse(
    query: JsonRecord,
    breakdown: WebBreakdown,
    anchor: number,
    refreshedAt: number | undefined
): WebQueryResponseApi {
    const window = windowOf(query, anchor)
    const properties = propertiesOf(query.properties)
    const own = new Set<string>()
    for (const [value] of TABLES[breakdown]) {
        for (const property of breakdownFilter(breakdown, value)?.properties ?? []) {
            own.add(property.key)
        }
    }
    // Regions and cities belong to a country, so the Country drill-down shows only that country's rows.
    const country =
        breakdown === 'Region' || breakdown === 'City'
            ? properties.find((active) => active.key === '$geoip_country_code' && active.operator === 'exact')
            : undefined
    const skip = country ? new Set([...own, country.key]) : own
    const total = ((VISITORS_PER_8_DAYS * windowDays(window).length) / 8) * filterScale(properties, skip)
    const limit = typeof query.limit === 'number' ? query.limit : 10
    const rows = TABLES[breakdown]
        .filter(([value]) => {
            const filter = breakdownFilter(breakdown, value)
            const ownMatch = properties.every(
                (active) =>
                    !own.has(active.key) ||
                    (filter?.properties.some((property) => sameProperty(property, active)) ?? false)
            )
            return ownMatch && (!country || (Array.isArray(value) && value[0] === country.value))
        })
        .map(([value, share, perVisitor = 3], index) => {
            const visitors = Math.max(1, Math.round(total * share))
            const previous = Math.max(1, Math.round(visitors * (0.82 + noise(index, 41 + hash(breakdown)) * 0.32)))
            return { value, visitors, previous, secondary: Math.round(visitors * perVisitor) }
        })
    const clicks = breakdown === 'ExitClick'
    return {
        columns: clicks
            ? ['context.columns.url', 'context.columns.visitors', 'context.columns.clicks']
            : [
                  'context.columns.breakdown_value',
                  'context.columns.visitors',
                  'context.columns.views',
                  'context.columns.ui_fill_fraction',
                  'context.columns.cross_sell',
              ],
        results: rows.slice(0, limit).map((row) => {
            const secondary = [row.secondary, Math.round((row.secondary * row.previous) / row.visitors)]
            return clicks
                ? [row.value, [row.visitors, row.previous], secondary]
                : [row.value, [row.visitors, row.previous], secondary, row.visitors / (rows[0]?.visitors ?? 1), '']
        }),
        hasMore: rows.length > limit,
        ...freshness(window, anchor, refreshedAt),
    }
}

function hourWeight(hour: number): number {
    return 0.25 + Math.exp(-((hour - 14) ** 2) / 18)
}

const HOUR_TOTAL = Array.from({ length: 24 }, (_, hour) => hourWeight(hour)).reduce((sum, value) => sum + value, 0)

const VISITORS_PER_DAY = VISITORS_PER_8_DAYS / 8

function dayValue(metric: WebTrendMetric, day: Date, anchor: Date): number {
    const index = Math.round(startOfDay(day).getTime() / DAY)
    const back = Math.round((startOfDay(anchor).getTime() - startOfDay(day).getTime()) / DAY)
    const weekend = day.getDay() === 0 || day.getDay() === 6 ? 0.72 : 1
    const visitors = VISITORS_PER_DAY * weekend * (1 - back * 0.002) * (0.88 + noise(index, 21) * 0.24)
    switch (metric) {
        case 'visitors':
            return visitors
        case 'views':
            return visitors * 3.7 * (0.95 + noise(index, 22) * 0.1)
        case 'sessions':
            return visitors * 1.3 * (0.97 + noise(index, 23) * 0.06)
        case 'session duration':
            return 194 * (0.88 + noise(index, 24) * 0.24)
        case 'bounce rate':
            return 0.416 * (0.9 + noise(index, 25) * 0.2)
    }
}

function isAverage(metric: WebTrendMetric): boolean {
    return metric === 'session duration' || metric === 'bounce rate'
}

type DemoInterval = 'hour' | 'day' | 'week' | 'month'

function startOfHour(at: number): Date {
    const date = new Date(at)
    date.setMinutes(0, 0, 0)
    return date
}

function bucketStarts(window: DemoWindow, interval: DemoInterval, dateFrom: string | null, anchor: Date): Date[] {
    const starts: Date[] = []
    const lastDay = window.end
    switch (interval) {
        case 'hour': {
            const hours = dateFrom ? /^-(\d+)h$/.exec(dateFrom) : null
            const first = hours ? startOfHour(anchor.getTime() - Number(hours[1]) * HOUR) : window.start
            const endsToday = isoDay(lastDay) === isoDay(anchor)
            const last = endsToday ? startOfHour(anchor.getTime()) : new Date(addDays(lastDay, 1).getTime() - HOUR)
            for (let at = first.getTime(); at <= last.getTime(); at += HOUR) {
                starts.push(new Date(at))
            }
            return starts
        }
        case 'day':
            return windowDays(window)
        case 'week':
            for (let day = addDays(window.start, -window.start.getDay()); day <= lastDay; day = addDays(day, 7)) {
                starts.push(day)
            }
            return starts
        case 'month':
            for (
                let day = new Date(window.start.getFullYear(), window.start.getMonth(), 1);
                day <= lastDay;
                day = new Date(day.getFullYear(), day.getMonth() + 1, 1)
            ) {
                starts.push(day)
            }
            return starts
    }
}

function bucketEnd(start: Date, interval: DemoInterval): Date {
    switch (interval) {
        case 'hour':
            return new Date(start.getTime() + HOUR)
        case 'day':
            return addDays(start, 1)
        case 'week':
            return addDays(start, 7)
        case 'month':
            return new Date(start.getFullYear(), start.getMonth() + 1, 1)
    }
}

function bucketLabel(start: Date, interval: DemoInterval): string {
    return interval === 'hour' ? `${isoDay(start)} ${String(start.getHours()).padStart(2, '0')}:00:00` : isoDay(start)
}

function bucketValue(
    metric: WebTrendMetric,
    start: Date,
    interval: DemoInterval,
    window: DemoWindow,
    anchor: Date
): number {
    const now = anchor.getTime()
    if (interval === 'hour') {
        const day = dayValue(metric, start, anchor)
        if (isAverage(metric)) {
            return day * (0.9 + noise(Math.round(start.getTime() / HOUR), 26) * 0.2)
        }
        const share = (hourWeight(start.getHours()) / HOUR_TOTAL) * Math.min(1, (now - start.getTime()) / HOUR)
        return day * Math.max(0, share)
    }
    const end = bucketEnd(start, interval)
    const values: number[] = []
    for (let day = start; day < end; day = addDays(day, 1)) {
        if (day < window.start || day > window.end || day.getTime() > now) {
            continue
        }
        const part = Math.min(1, (now - day.getTime()) / DAY)
        values.push(dayValue(metric, day, anchor) * (isAverage(metric) ? 1 : part))
    }
    if (values.length === 0) {
        return 0
    }
    const sum = values.reduce((total, value) => total + value, 0)
    // People come back on several days, so a week's or month's visitors are fewer than the sum of its days.
    return isAverage(metric) ? sum / values.length : sum * (metric === 'visitors' && values.length > 1 ? 0.82 : 1)
}

const METRIC_MATH: Record<string, WebTrendMetric> = { dau: 'visitors', total: 'views', unique_session: 'sessions' }

function trendMetric(series: JsonRecord | undefined): WebTrendMetric {
    if (series?.math_property === '$session_duration') {
        return 'session duration'
    }
    if (series?.math_property === '$is_bounce') {
        return 'bounce rate'
    }
    return METRIC_MATH[String(series?.math)] ?? 'visitors'
}

function trendResponse(query: JsonRecord, anchor: number, refreshedAt: number | undefined): WebQueryResponseApi {
    const window = windowOf(query, anchor)
    const anchorDate = new Date(anchor)
    const range = asRecord(query.dateRange) ?? {}
    const interval = (
        ['hour', 'week', 'month'].includes(String(query.interval)) ? query.interval : 'day'
    ) as DemoInterval
    const series = asRecord(Array.isArray(query.series) ? query.series[0] : undefined)
    const metric = trendMetric(series)
    const properties = propertiesOf(query.properties)
    const scale = isAverage(metric) ? 1 : filterScale(properties)
    const starts = bucketStarts(
        window,
        interval,
        typeof range.date_from === 'string' ? range.date_from : null,
        anchorDate
    )
    const first = starts[0]
    const span = first ? bucketEnd(starts[starts.length - 1] ?? first, interval).getTime() - first.getTime() : 0
    const previousWindow: DemoWindow = {
        start: new Date(window.start.getTime() - span),
        end: new Date(window.end.getTime() - span),
    }
    const round = (value: number): number =>
        isAverage(metric) ? Math.round(value * 1000) / 1000 : Math.round(value * scale)
    const entry = (label: 'current' | 'previous', buckets: Date[], data: number[]): JsonRecord => ({
        action: { order: 0, math: series?.math ?? 'dau' },
        label: typeof series?.custom_name === 'string' ? series.custom_name : 'Pageview',
        compare: true,
        compare_label: label,
        days: buckets.map((start) => bucketLabel(start, interval)),
        labels: buckets.map((start) => bucketLabel(start, interval)),
        data,
        count: data.reduce((total, value) => total + value, 0),
    })
    const previousStarts = starts.map((start) => new Date(start.getTime() - span))
    return {
        results: [
            entry(
                'current',
                starts,
                starts.map((start) => round(bucketValue(metric, start, interval, window, anchorDate)))
            ),
            entry(
                'previous',
                previousStarts,
                previousStarts.map((start) => round(bucketValue(metric, start, interval, previousWindow, anchorDate)))
            ),
        ],
        ...freshness(window, anchor, refreshedAt),
    }
}

const RETENTION_CURVE = [100, 26, 17, 13, 11]

function retentionResponse(query: JsonRecord, anchor: number, refreshedAt: number | undefined): WebQueryResponseApi {
    const requested = windowOf(query, anchor)
    const scale = filterScale(propertiesOf(query.properties))
    const today = startOfDay(new Date(anchor))
    const lastStart = addDays(requested.end, -requested.end.getDay())
    const weeks = RETENTION_CURVE.length
    const results = Array.from({ length: weeks }, (_, cohort) => {
        const start = addDays(lastStart, (cohort - weeks + 1) * 7)
        const size = Math.max(1, Math.round(1900 * scale * (0.9 + noise(cohort, 31) * 0.2)))
        const values = RETENTION_CURVE.map((percent, week) => {
            const started = addDays(start, week * 7) <= today
            const jitter = week === 0 ? 1 : 0.9 + noise(cohort * 8 + week, 32) * 0.2
            return { count: started ? Math.round(size * (percent / 100) * jitter) : 0, label: `Week ${week}` }
        })
        return {
            date: `${isoDay(start)}T00:00:00${offsetSuffix(start)}`,
            label: `Week ${cohort}`,
            values,
            breakdown_value: null,
        }
    })
    const window = { start: addDays(lastStart, -(weeks - 1) * 7), end: requested.end }
    return { results, ...freshness(window, anchor, refreshedAt) }
}

function activeHoursResponse(query: JsonRecord, anchor: number, refreshedAt: number | undefined): WebQueryResponseApi {
    const window = windowOf(query, anchor)
    const anchorDate = new Date(anchor)
    const series = asRecord(Array.isArray(query.series) ? query.series[0] : undefined)
    const scale = filterScale(propertiesOf(series?.properties))
    const cells = new Map<string, { row: number; column: number; value: number }>()
    for (const day of windowDays(window)) {
        const row = ((day.getDay() + 6) % 7) + 1
        const visitors = dayValue('visitors', day, anchorDate) * scale
        for (let hour = 0; hour < 24; hour++) {
            const start = new Date(day.getFullYear(), day.getMonth(), day.getDate(), hour)
            if (start.getTime() > anchor) {
                break
            }
            const key = `${row}:${hour}`
            const cell = cells.get(key) ?? { row, column: hour, value: 0 }
            cell.value += (visitors * hourWeight(hour) * 1.35) / HOUR_TOTAL
            cells.set(key, cell)
        }
    }
    const data = [...cells.values()].map((cell) => ({ ...cell, value: Math.round(cell.value) }))
    const sum = data.reduce((total, cell) => total + cell.value, 0)
    return {
        results: [
            {
                label: '$pageview',
                data: [],
                aggregated_value: Math.round(sum * 0.6),
                count: Math.round(sum * 0.6),
                calendar_heatmap_data: {
                    data,
                    rowAggregations: [],
                    columnAggregations: [],
                    allAggregations: Math.round(sum * 0.6),
                },
            },
        ],
        ...freshness(window, anchor, refreshedAt),
    }
}

export function demoWebQueryResponse(query: JsonRecord, anchor: number, refreshedAt?: number): WebQueryResponseApi {
    switch (query.kind) {
        case 'WebStatsTableQuery': {
            const breakdown = query.breakdownBy as WebBreakdown
            return TABLES[breakdown] ? tableResponse(query, breakdown, anchor, refreshedAt) : { results: [] }
        }
        case 'WebExternalClicksTableQuery':
            return tableResponse(query, 'ExitClick', anchor, refreshedAt)
        case 'RetentionQuery':
            return retentionResponse(query, anchor, refreshedAt)
        case 'TrendsQuery':
            return asRecord(query.trendsFilter)?.display === 'CalendarHeatmap'
                ? activeHoursResponse(query, anchor, refreshedAt)
                : trendResponse(query, anchor, refreshedAt)
        default:
            return { results: [] }
    }
}
