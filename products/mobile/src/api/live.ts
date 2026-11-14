import { hostKind } from '@/lib/environment'
import { isRecord } from '@/lib/records'
import { apiJson, projectPath, scopedPath } from './client'
import { runQuery } from './query'
import type { ProjectScope } from './reports'

// The Live screen's reads. The HogQL text follows `loadQueryData` in the web's
// `frontend/src/scenes/web-analytics/LiveMetricsDashboard/liveWebAnalyticsMetricsLogic.tsx`, in its unfiltered form
// (`values` for the window instead of `{filters}`), without the bot traffic columns.

export type LiveQueryKey =
    | 'platforms'
    | 'mobileMetrics'
    | 'mobileSessions'
    | 'usersPageviews'
    | 'device'
    | 'browser'
    | 'paths'
    | 'screens'
    | 'referrer'
    | 'geo'
    | 'recentEvents'
    | 'usersOnline'

export const LIVE_WINDOW_MINUTES = 30
const MINUTE_MS = 60_000

export interface LiveWindow {
    dateFrom: string
    dateTo: string
}

/**
 * Starts at the first of the 30 minutes on screen, so no partial minute counts in the totals. Ends a minute after now,
 * so an event with a slightly fast client clock still shows.
 */
export function liveWindow(now: number): LiveWindow {
    const currentMinute = Math.floor(now / MINUTE_MS) * MINUTE_MS
    return {
        dateFrom: new Date(currentMinute - (LIVE_WINDOW_MINUTES - 1) * MINUTE_MS).toISOString(),
        dateTo: new Date(now + MINUTE_MS).toISOString(),
    }
}

export interface HogQLResponseApi {
    results?: unknown[][] | null
    columns?: string[] | null
    timezone?: string | null
}

export interface LivePathsResultApi {
    breakdown_value?: unknown
    data?: unknown
}

export interface LivePathsResponseApi {
    results?: LivePathsResultApi[] | null
}

/** The fields of `GET api/projects/{id}/` that Live reads (`ProjectBackwardCompatSerializer`). */
export interface LiveProjectApi {
    /** Null unless the grant covers `query:read`. */
    live_events_token?: string | null
    timezone?: string | null
    path_cleaning_filters?: unknown[] | null
    /** False until the project ingests its first event. */
    ingested_event?: boolean | null
}

export interface LiveStatsApi {
    users_on_product?: number | null
}

export const MOBILE_EVENT = `(properties.$lib IN ('posthog-ios', 'posthog-android') OR (properties.$lib IN ('posthog-react-native', 'posthog-flutter', 'posthog-kmp') AND lower(properties.$os) IN ('ios', 'ipados', 'android')) OR (event = '$screen' AND (properties.$lib IS NULL OR properties.$lib = '') AND lower(properties.$os) IN ('ios', 'ipados', 'android'))) AND event NOT IN ('$feature_flag_called', '$identify', '$set', '$set_once', '$groupidentify', '$exception', '$snapshot', 'Application Backgrounded')`

export const WEB_EVENT = `(properties.$lib IN ('web', 'js', 'posthog-js') OR (event IN ('$pageview', '$pageleave') AND (properties.$lib IS NULL OR properties.$lib = ''))) `

const WHERE_WINDOW = 'timestamp >= toDateTime({dateFrom}) AND timestamp <= toDateTime({dateTo})'
const WHERE_VISIBLE_MINUTES =
    'timestamp >= toDateTime({dateFrom}) AND timestamp < toStartOfMinute(toDateTime({dateTo}))'

function tags(name: string): Record<string, string> {
    return { productKey: 'web_analytics', scene: 'web-analytics-live', name }
}

function hogql(query: string, name: string, window: LiveWindow): Record<string, unknown> {
    return { kind: 'HogQLQuery', query, values: { dateFrom: window.dateFrom, dateTo: window.dateTo }, tags: tags(name) }
}

const DEVICE_ID = `if(
    properties.$device_id IS NULL OR properties.$device_id = '$posthog_cookieless',
    concat('cookieless_transform|||', ifNull(properties.$ip, ''), '|||', ifNull(properties.$raw_user_agent, '')),
    properties.$device_id
)`

function breakdownQuery(
    category: string,
    id: string,
    name: string,
    window: LiveWindow,
    where: string = WHERE_VISIBLE_MINUTES
): Record<string, unknown> {
    return hogql(
        `SELECT groupArray((category, visitor_count))
        FROM (
            SELECT ${category} AS category, uniqExact(${id}) AS visitor_count
            FROM events
            WHERE ${where}
            GROUP BY category
        )`,
        name,
        window
    )
}

function topViewsQuery(
    event: string,
    breakdown: string,
    name: string,
    window: LiveWindow,
    pathCleaning: boolean
): Record<string, unknown> {
    return {
        kind: 'TrendsQuery',
        interval: 'minute',
        series: [{ kind: 'EventsNode', event, math: 'total' }],
        breakdownFilter: {
            breakdown_type: 'event',
            breakdown,
            breakdown_limit: 10,
            breakdown_hide_other_aggregation: true,
            breakdown_path_cleaning: pathCleaning,
        },
        dateRange: { date_from: window.dateFrom, date_to: window.dateTo },
        properties: [],
        filterTestAccounts: false,
        tags: tags(name),
    }
}

export interface LiveQueryOptions {
    window: LiveWindow
    pathCleaning: boolean
    mobileOnly?: boolean
    webOnly?: boolean
}

export function liveQuery(
    key: LiveQueryKey,
    { window, pathCleaning, mobileOnly = false, webOnly = false }: LiveQueryOptions
): Record<string, unknown> {
    const audienceWhere = mobileOnly ? MOBILE_EVENT : webOnly ? WEB_EVENT : null
    const visibleWhere = audienceWhere ? `${WHERE_VISIBLE_MINUTES} AND ${audienceWhere}` : WHERE_VISIBLE_MINUTES
    const windowWhere = audienceWhere ? `${WHERE_WINDOW} AND ${audienceWhere}` : WHERE_WINDOW
    switch (key) {
        case 'platforms':
            return breakdownQuery(
                "if(lower(properties.$os) IN ('ios', 'ipados'), 'iOS', if(lower(properties.$os) = 'android', 'Android', 'Other'))",
                'distinct_id',
                'live_platforms',
                window,
                `${WHERE_VISIBLE_MINUTES} AND ${MOBILE_EVENT}`
            )
        case 'mobileSessions':
            return hogql(
                `SELECT uniqExactIf(properties.$session_id, properties.$session_id IS NOT NULL AND properties.$session_id != ''), countIf(properties.$session_id IS NOT NULL AND properties.$session_id != '') FROM events WHERE ${WHERE_VISIBLE_MINUTES} AND ${MOBILE_EVENT}`,
                'live_mobile_sessions',
                window
            )
        case 'mobileMetrics':
            return {
                kind: 'HogQLQuery',
                query: `SELECT uniqIf(distinct_id, timestamp >= now() - INTERVAL 1 DAY), uniq(distinct_id), countIf(event = 'Application Installed' AND timestamp >= now() - INTERVAL 1 DAY), countIf(event = 'Application Installed'), count() FROM events WHERE timestamp >= now() - INTERVAL 7 DAY AND timestamp <= now() AND ${MOBILE_EVENT}`,
                tags: tags('live_mobile_metrics'),
            }
        case 'usersPageviews':
            return hogql(
                `SELECT
                    toUnixTimestamp64Milli(toDateTime64(minute_bucket, 3)) AS minute_ms,
                    count() AS users,
                    countIf(minute_bucket = first_minute) AS new_users,
                    sum(minute_pageviews) AS pageviews,
                    sum(minute_screenviews) AS screenviews
                FROM (
                    SELECT
                        toStartOfMinute(timestamp) AS minute_bucket,
                        countIf(event = '$pageview') AS minute_pageviews,
                        countIf(event = '$screen') AS minute_screenviews,
                        min(minute_bucket) OVER (PARTITION BY distinct_id) AS first_minute
                    FROM events
                    WHERE ${visibleWhere}
                    GROUP BY distinct_id, minute_bucket
                )
                GROUP BY minute_bucket
                ORDER BY minute_bucket ASC`,
                'live_users_pageviews',
                window
            )
        case 'device':
            return breakdownQuery(
                "ifNull(properties.$device_type, 'Unknown')",
                DEVICE_ID,
                'live_device_breakdown',
                window,
                visibleWhere
            )
        case 'browser':
            return breakdownQuery(
                "ifNull(properties.$browser, 'Unknown')",
                DEVICE_ID,
                'live_browser_breakdown',
                window,
                visibleWhere
            )
        case 'paths':
            return {
                ...topViewsQuery('$pageview', '$pathname', 'live_paths', window, pathCleaning),
                ...(webOnly
                    ? {
                          properties: {
                              type: 'AND',
                              values: [
                                  {
                                      type: 'OR',
                                      values: [
                                          {
                                              key: '$lib',
                                              type: 'event',
                                              operator: 'exact',
                                              value: ['web', 'js', 'posthog-js', ''],
                                          },
                                          { key: '$lib', type: 'event', operator: 'is_not_set' },
                                      ],
                                  },
                              ],
                          },
                      }
                    : {}),
            }
        case 'screens':
            // The `$screen` form of `paths`, for projects that send app events and no pageviews. Path cleaning rules
            // are written for URL paths, so they do not apply to screen names.
            return mobileOnly
                ? hogql(
                      `SELECT properties.$screen_name, count() FROM events WHERE ${visibleWhere} AND event = '$screen' GROUP BY properties.$screen_name ORDER BY count() DESC LIMIT 10`,
                      'live_screens',
                      window
                  )
                : topViewsQuery('$screen', '$screen_name', 'live_screens', window, false)
        case 'referrer':
            return hogql(
                `SELECT
                    toStartOfMinute(timestamp) AS minute_bucket,
                    if(isNotNull(properties.$referring_domain) AND properties.$referring_domain != '', properties.$referring_domain, '$direct') AS referring_domain,
                    count() AS view_count
                FROM events
                WHERE ${windowWhere}
                    AND event = '$pageview'
                GROUP BY minute_bucket, referring_domain
                ORDER BY minute_bucket ASC`,
                'live_referrers',
                window
            )
        case 'geo':
            return breakdownQuery(
                'properties.$geoip_country_code',
                'distinct_id',
                'live_geo',
                window,
                `${visibleWhere} AND properties.$geoip_country_code IS NOT NULL AND properties.$geoip_country_code != ''`
            )
        case 'recentEvents':
            // Epoch milliseconds instead of the web's `toString(timestamp)`, which is wall-clock time in the project's
            // time zone with no offset, so the phone could not place it in its own time zone.
            return hogql(
                `SELECT uuid, event, distinct_id, toUnixTimestamp64Milli(timestamp),
                    properties.$current_url, properties.$screen_name, properties.$pathname, properties.$session_id
                FROM events
                WHERE ${windowWhere}
                ORDER BY timestamp DESC
                LIMIT 50`,
                'live_recent_events',
                window
            )
        case 'usersOnline':
            // The web header badge's fallback count. It reads its own window, so it carries no values.
            return {
                kind: 'HogQLQuery',
                query: `SELECT uniq(distinct_id)
                    FROM events
                    WHERE timestamp > now() - INTERVAL 1 MINUTE
                        AND timestamp < now() + INTERVAL 1 MINUTE`,
                tags: tags('live_users_count'),
            }
    }
}

/**
 * One job through `POST query/` on the Live budget. No status polls: a response that still runs has no `results`, and
 * the screen keeps that part's last value until the next read.
 */
export async function fetchLiveQuery(
    query: Record<string, unknown>,
    signal?: AbortSignal,
    scope?: ProjectScope
): Promise<unknown> {
    return runQuery(query, { refresh: 'blocking', poll: false, budgetFamily: 'live', signal, scope })
}

export async function fetchLiveProject(signal?: AbortSignal, scope?: ProjectScope): Promise<LiveProjectApi> {
    const body = await apiJson<unknown>(scope ? scopedPath(scope, '') : projectPath(''), { signal })
    return isRecord(body) ? (body as LiveProjectApi) : {}
}

export function liveStatsHost(host: string): string | null {
    switch (hostKind(host)) {
        case 'cloud-us':
            return 'https://live.us.posthog.com'
        case 'cloud-eu':
            return 'https://live.eu.posthog.com'
        default:
            return null
    }
}

/** Shorter than the 10-second poll, so a hung request never overlaps the next one. */
const LIVE_STATS_TIMEOUT_MS = 8000

export class LiveStatsError extends Error {
    constructor(status: number) {
        super(`Live stats failed with status ${status}`)
        this.name = 'LiveStatsError'
    }
}

/**
 * Users online from the live events service. A plain `fetch`: the service is another host, takes the project's live
 * events token instead of the session's, and has no PostHog API budget.
 */
export async function fetchLiveStats(liveHost: string, token: string, signal?: AbortSignal): Promise<LiveStatsApi> {
    const controller = new AbortController()
    const abort = (): void => controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(abort, LIVE_STATS_TIMEOUT_MS)
    try {
        const response = await fetch(`${liveHost}/stats`, {
            headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
            signal: controller.signal,
        })
        if (!response.ok) {
            throw new LiveStatsError(response.status)
        }
        const body: unknown = await response.json()
        return isRecord(body) ? (body as LiveStatsApi) : {}
    } finally {
        clearTimeout(timer)
        signal?.removeEventListener('abort', abort)
    }
}
