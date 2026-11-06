import type { HogQLResponseApi, LivePathsResponseApi, LiveStatsApi } from '@/api/live'
import { isRecord } from '@/lib/records'
import type {
    LiveActivity,
    LiveBreakdown,
    LiveBreakdownKind,
    LiveBreakdownRow,
    LiveEventKind,
    LiveEventRow,
    LiveMinute,
    LiveRankedRow,
} from '@/model/live'

// Live query responses -> Live view models. The rules follow the web's `LiveMetricsSlidingWindow`: a visitor is new in
// the first minute of the window that shows them and returning after that, breakdown counts are distinct ids, and top
// lists rank by views.

const MINUTE_MS = 60_000
export const LIVE_MINUTES = 30
export const LIVE_TOP_ROWS = 10
/** The web's top browsers and countries; the rest add up to an "Other" row. */
const BREAKDOWN_TOP_ROWS = 6
export const DIRECT_REFERRER = '$direct'
const OTHER = 'Other'
const BREAKDOWN_PLACEHOLDER = '$$_posthog_breakdown_'

function rowsOf(response: unknown): unknown[][] {
    const results = isRecord(response) ? (response as HogQLResponseApi).results : undefined
    return Array.isArray(results) ? results.filter((row): row is unknown[] => Array.isArray(row)) : []
}

function numberOf(value: unknown): number {
    const number = typeof value === 'string' ? Number(value) : value
    return typeof number === 'number' && Number.isFinite(number) ? number : 0
}

function textOf(value: unknown): string | null {
    if (typeof value === 'string') {
        return value === '' ? null : value
    }
    return typeof value === 'number' ? String(value) : null
}

function minuteOf(value: unknown): number {
    const at = typeof value === 'number' ? value : typeof value === 'string' ? Date.parse(value) : Number.NaN
    return Number.isFinite(at) ? Math.floor(at / MINUTE_MS) * MINUTE_MS : Number.NaN
}

export function liveMinuteStarts(now: number): number[] {
    const current = Math.floor(now / MINUTE_MS) * MINUTE_MS
    return Array.from({ length: LIVE_MINUTES }, (_, index) => current - (LIVE_MINUTES - 1 - index) * MINUTE_MS)
}

/** The chart and the totals from the `usersPageviews` rows `[minute, distinct ids, pageviews]`. */
export function liveActivity(response: unknown, now: number): LiveActivity {
    const byMinute = new Map<number, { ids: string[]; pageviews: number }>()
    for (const row of rowsOf(response)) {
        const at = minuteOf(row[0])
        if (!Number.isFinite(at)) {
            continue
        }
        const ids = Array.isArray(row[1]) ? row[1].filter((id): id is string => typeof id === 'string') : []
        const bucket = byMinute.get(at) ?? { ids: [], pageviews: 0 }
        bucket.ids.push(...ids)
        bucket.pageviews += numberOf(row[2])
        byMinute.set(at, bucket)
    }
    const seen = new Set<string>()
    let pageviews = 0
    const minutes = liveMinuteStarts(now).map((at): LiveMinute => {
        const bucket = byMinute.get(at)
        const ids = new Set(bucket?.ids ?? [])
        let newUsers = 0
        for (const id of ids) {
            if (!seen.has(id)) {
                newUsers += 1
                seen.add(id)
            }
        }
        pageviews += bucket?.pageviews ?? 0
        return {
            at,
            users: ids.size,
            newUsers,
            returningUsers: ids.size - newUsers,
            pageviews: bucket?.pageviews ?? 0,
        }
    })
    return { minutes, uniqueVisitors: seen.size, pageviews }
}

export function livePathCounts(response: unknown): Map<string, number> {
    const counts = new Map<string, number>()
    const results = isRecord(response) ? (response as LivePathsResponseApi).results : undefined
    for (const result of Array.isArray(results) ? results : []) {
        const path = textOf(result?.breakdown_value)
        // Pageviews without a path come back under the trends runner's null placeholder.
        if (!path || path.startsWith(BREAKDOWN_PLACEHOLDER)) {
            continue
        }
        const data = Array.isArray(result.data) ? result.data : []
        counts.set(path, (counts.get(path) ?? 0) + data.reduce<number>((sum, value) => sum + numberOf(value), 0))
    }
    return counts
}

export function liveReferrerCounts(response: unknown): Map<string, number> {
    const counts = new Map<string, number>()
    for (const row of rowsOf(response)) {
        const domain = textOf(row[1]) ?? DIRECT_REFERRER
        counts.set(domain, (counts.get(domain) ?? 0) + numberOf(row[2]))
    }
    return counts
}

/**
 * The top rows by views, each with its share of the window's pageviews and how many places it moved since `previous`.
 * Ties keep a stable order, so equal counts never swap places between reads.
 */
export function liveRankedRows(
    counts: ReadonlyMap<string, number>,
    totalPageviews: number,
    previous: readonly LiveRankedRow[] | null
): LiveRankedRow[] {
    const before = new Map((previous ?? []).map((row, index) => [row.key, index]))
    return [...counts.entries()]
        .filter(([, views]) => views > 0)
        .sort(
            ([a, aViews], [b, bViews]) =>
                bViews - aViews || (before.get(a) ?? 99) - (before.get(b) ?? 99) || (a < b ? -1 : 1)
        )
        .slice(0, LIVE_TOP_ROWS)
        .map(([key, views], index): LiveRankedRow => {
            const was = before.get(key)
            const moved = was === undefined ? 0 : was - index
            return {
                key,
                label: key === DIRECT_REFERRER ? 'Direct / None' : key,
                views,
                percent: totalPageviews > 0 ? (views / totalPageviews) * 100 : 0,
                rankDelta: moved === 0 ? null : moved,
                direct: key === DIRECT_REFERRER,
            }
        })
}

const STAT_LABELS: Record<LiveBreakdownKind, string> = {
    devices: 'unique devices',
    browsers: 'unique browsers',
    countries: 'unique visitors',
}

/**
 * Distinct ids per device type, browser or country from the `[minute, {value: ids}]` rows of the minutes on screen.
 * Browsers and countries keep their top six and add the rest up as "Other", which always comes last.
 */
export function liveBreakdown(response: unknown, kind: LiveBreakdownKind, now: number): LiveBreakdown {
    const minutes = new Set(liveMinuteStarts(now))
    const ids = new Map<string, Set<string>>()
    for (const row of rowsOf(response)) {
        if (!minutes.has(minuteOf(row[0])) || !isRecord(row[1])) {
            continue
        }
        for (const [value, list] of Object.entries(row[1])) {
            const set = ids.get(value) ?? new Set<string>()
            for (const id of Array.isArray(list) ? list : []) {
                if (typeof id === 'string') {
                    set.add(id)
                }
            }
            ids.set(value, set)
        }
    }
    const counted = [...ids.entries()]
        .map(([key, set]) => ({ key, count: set.size }))
        .filter((entry) => entry.count > 0)
        .sort((a, b) => b.count - a.count || (a.key < b.key ? -1 : 1))
    const total = counted.reduce((sum, entry) => sum + entry.count, 0)
    const limited =
        kind === 'devices' || counted.length <= BREAKDOWN_TOP_ROWS
            ? counted
            : [
                  ...counted.slice(0, BREAKDOWN_TOP_ROWS),
                  {
                      key: OTHER,
                      count: counted.slice(BREAKDOWN_TOP_ROWS).reduce((sum, entry) => sum + entry.count, 0),
                  },
              ]
    const rows = limited.map(
        ({ key, count }): LiveBreakdownRow => ({
            key,
            label: kind === 'countries' && key !== OTHER ? countryName(key) : key,
            flag: kind === 'countries' && key !== OTHER ? countryFlag(key) : null,
            count,
            percent: total > 0 ? (count / total) * 100 : 0,
        })
    )
    return { statLabel: STAT_LABELS[kind], total, rows }
}

const EVENT_LABELS: Record<string, string> = {
    $pageview: 'Pageview',
    $screen: 'Screen',
    $pageleave: 'Pageleave',
    $autocapture: 'Autocapture',
    $identify: 'Identify',
    $exception: 'Exception',
}

function eventKind(event: string): LiveEventKind {
    return event === '$pageview' ? 'pageview' : event === '$screen' ? 'screen' : 'other'
}

/** The newest events first, from `[uuid, event, distinct id, epoch ms, url, screen, path, session]` rows. */
export function liveEvents(response: unknown): LiveEventRow[] {
    const events: LiveEventRow[] = []
    for (const row of rowsOf(response)) {
        const id = textOf(row[0])
        const event = textOf(row[1])
        if (!id || !event) {
            continue
        }
        const at = typeof row[3] === 'number' ? row[3] : typeof row[3] === 'string' ? Number(row[3]) : Number.NaN
        const url = textOf(row[4])
        events.push({
            id,
            event,
            label: EVENT_LABELS[event] ?? event,
            kind: eventKind(event),
            distinctId: textOf(row[2]) ?? '',
            place: textOf(row[6]) ?? textOf(row[5]) ?? url,
            url,
            sessionId: textOf(row[7]),
            at: Number.isFinite(at) ? at : Number.NaN,
        })
    }
    return events.sort((a, b) => (Number.isFinite(b.at) ? b.at : 0) - (Number.isFinite(a.at) ? a.at : 0))
}

export function liveUsersOnlineFromStats(body: LiveStatsApi): number | null {
    const value = body.users_on_product
    return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.round(value) : null
}

export function liveUsersOnlineFromQuery(response: unknown): number | null {
    const first = rowsOf(response)[0]?.[0]
    if (first === undefined || first === null) {
        return null
    }
    const value = numberOf(first)
    return value >= 0 ? Math.round(value) : null
}

export function countryFlag(code: string): string | null {
    const upper = code.toUpperCase()
    if (!/^[A-Z]{2}$/.test(upper)) {
        return null
    }
    return String.fromCodePoint(...[...upper].map((letter) => 0x1f1e6 + letter.charCodeAt(0) - 65))
}

// Hermes has no `Intl.DisplayNames`, so the phone names the most common countries itself and shows the code otherwise.
const COUNTRY_NAMES: Record<string, string> = {
    AE: 'United Arab Emirates',
    AR: 'Argentina',
    AT: 'Austria',
    AU: 'Australia',
    BD: 'Bangladesh',
    BE: 'Belgium',
    BG: 'Bulgaria',
    BR: 'Brazil',
    CA: 'Canada',
    CH: 'Switzerland',
    CL: 'Chile',
    CN: 'China',
    CO: 'Colombia',
    CZ: 'Czechia',
    DE: 'Germany',
    DK: 'Denmark',
    EG: 'Egypt',
    ES: 'Spain',
    FI: 'Finland',
    FR: 'France',
    GB: 'United Kingdom',
    GR: 'Greece',
    HK: 'Hong Kong',
    HU: 'Hungary',
    ID: 'Indonesia',
    IE: 'Ireland',
    IL: 'Israel',
    IN: 'India',
    IT: 'Italy',
    JP: 'Japan',
    KE: 'Kenya',
    KR: 'South Korea',
    MX: 'Mexico',
    MY: 'Malaysia',
    NG: 'Nigeria',
    NL: 'Netherlands',
    NO: 'Norway',
    NZ: 'New Zealand',
    PH: 'Philippines',
    PK: 'Pakistan',
    PL: 'Poland',
    PT: 'Portugal',
    RO: 'Romania',
    RU: 'Russia',
    SA: 'Saudi Arabia',
    SE: 'Sweden',
    SG: 'Singapore',
    TH: 'Thailand',
    TR: 'Türkiye',
    TW: 'Taiwan',
    UA: 'Ukraine',
    US: 'United States',
    VN: 'Vietnam',
    ZA: 'South Africa',
}

export function countryName(code: string): string {
    return COUNTRY_NAMES[code.toUpperCase()] ?? code
}
