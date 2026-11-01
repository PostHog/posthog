import { apiJson, projectPath } from './client'
import { runQuery } from './query'
import { type ProjectScope, scopeKey } from './reports'

// Shapes follow `SessionRecordingSerializer` and `MinimalPersonSerializer` in
// `posthog/session_recordings/session_recording_api.py` and `posthog/api/person.py`, keeping the fields the app reads.
// Every call here needs `session_recording:read`, except the events timeline, which is a `query:read` HogQL query.

export interface RecordingPersonApi {
    name?: string | null
    distinct_ids?: string[]
    properties?: Record<string, unknown> | null
}

export interface RecordingApi {
    id: string
    distinct_id?: string | null
    viewed?: boolean
    /** Seconds. */
    recording_duration?: number | null
    active_seconds?: number | null
    start_time?: string | null
    end_time?: string | null
    click_count?: number | null
    keypress_count?: number | null
    console_error_count?: number | null
    start_url?: string | null
    person?: RecordingPersonApi | null
    ongoing?: boolean
    activity_score?: number | null
}

export interface RecordingsListApi {
    results?: RecordingApi[]
    has_next?: boolean
    next_cursor?: string | null
}

export const RECENT_RECORDINGS_LIMIT = 10
/** The list window, the same as the watch feed's default, so both sides of the merged list cover the same days. */
export const RECENT_RECORDINGS_FROM = '-7d'

export async function fetchRecording(sessionId: string, signal?: AbortSignal): Promise<RecordingApi> {
    return apiJson<RecordingApi>(projectPath(`session_recordings/${encodeURIComponent(sessionId)}/`), { signal })
}

/**
 * `GET session_recordings/`, newest first: the server's default order is `start_time`
 * descending. The REST listing takes `session_recording:read`; the web's `RecordingsQuery` through `query/` would not
 * check that scope.
 */
export async function fetchRecentRecordings(signal?: AbortSignal, after?: string): Promise<RecordingsListApi> {
    return apiJson<RecordingsListApi>(projectPath('session_recordings/'), {
        query: { limit: RECENT_RECORDINGS_LIMIT, date_from: RECENT_RECORDINGS_FROM, after },
        signal,
    })
}

export const SESSION_EVENT_COLUMNS = [
    'timestamp',
    'event',
    'current_url',
    'pathname',
    'screen_name',
    'element_texts',
    'event_type',
    'issue_id',
    'exception_types',
    'exception_values',
    'browser',
    'os',
    'city',
] as const

/** Page views and clicks are many, so their query is capped; a session past the cap shows its first events. */
export const SESSION_ACTIVITY_LIMIT = 300
/** Errors and rage clicks are rare, so their own query keeps them even when page views and clicks hit the cap. */
export const SESSION_PROBLEMS_LIMIT = 100
/** Events can arrive a little before the first snapshot or after the last one. */
const WINDOW_PADDING_MS = 60_000

export type SessionEventsPart = 'activity' | 'problems'

const PART_FILTERS: Record<SessionEventsPart, string> = {
    activity:
        "AND (event IN ('$pageview', '$screen') OR (event = '$autocapture' AND properties.$event_type = 'click'))",
    problems: "AND event IN ('$rageclick', '$exception')",
}

const PART_LIMITS: Record<SessionEventsPart, number> = {
    activity: SESSION_ACTIVITY_LIMIT,
    problems: SESSION_PROBLEMS_LIMIT,
}

/**
 * One part of what happened in a session. The session id and the time window go in as `values`, never into the query
 * text. The window keeps ClickHouse on the recording's own days instead of the whole events table.
 */
export function sessionEventsQuery(
    sessionId: string,
    startTime: string,
    endTime: string,
    part: SessionEventsPart
): Record<string, unknown> {
    const from = new Date(new Date(startTime).getTime() - WINDOW_PADDING_MS).toISOString()
    const to = new Date(new Date(endTime).getTime() + WINDOW_PADDING_MS).toISOString()
    return {
        kind: 'HogQLQuery',
        query: [
            'SELECT timestamp, event, properties.$current_url, properties.$pathname, properties.$screen_name,',
            'elements_chain_texts, properties.$event_type, properties.$exception_issue_id,',
            'properties.$exception_types, properties.$exception_values, properties.$browser, properties.$os,',
            'properties.$geoip_city_name',
            'FROM events',
            'WHERE properties.$session_id = {session_id}',
            'AND timestamp >= toDateTime({date_from}) AND timestamp <= toDateTime({date_to})',
            PART_FILTERS[part],
            'ORDER BY timestamp ASC',
            `LIMIT ${PART_LIMITS[part]}`,
        ].join(' '),
        values: { session_id: sessionId, date_from: from, date_to: to },
    }
}

export interface SessionEventsResponseApi {
    results?: unknown[][]
}

export interface SessionEventsApi {
    activity: SessionEventsResponseApi
    problems: SessionEventsResponseApi
}

/** Both parts through `POST query/`, `blocking`, on the replay budget so Views refreshes never starve them. */
export async function fetchSessionEvents(
    sessionId: string,
    startTime: string,
    endTime: string,
    signal?: AbortSignal
): Promise<SessionEventsApi> {
    const run = async (part: SessionEventsPart): Promise<SessionEventsResponseApi> =>
        (await runQuery(sessionEventsQuery(sessionId, startTime, endTime, part), {
            signal,
            budgetFamily: 'replay',
        })) as SessionEventsResponseApi
    const [activity, problems] = await Promise.all([run('activity'), run('problems')])
    return { activity, problems }
}

export const recordingKeys = {
    all: (scope: ProjectScope | null) => ['recordings', ...scopeKey(scope)] as const,
    recent: (scope: ProjectScope | null) => [...recordingKeys.all(scope), 'recent', 'pages'] as const,
    detail: (scope: ProjectScope | null, sessionId: string) =>
        [...recordingKeys.all(scope), 'detail', sessionId] as const,
    events: (scope: ProjectScope | null, sessionId: string) =>
        [...recordingKeys.all(scope), 'events', sessionId] as const,
}
