import { apiJson, projectPath } from '@/api/client'
import { runQuery } from '@/api/query'
import type { RecordingsListApi } from '@/api/recordings'
import type { ObservationListApi } from '@/api/replayVision'

import type { FeedSource } from './feedModel'

export const FEED_PAGE_SIZE = 10
const FEED_FROM = '-7d'

interface RecordingFilter {
    type: 'recording'
    key: 'active_seconds' | 'duration'
    operator: 'gt' | 'lt'
    value: number
}

interface SourceQuery {
    order: 'start_time' | 'activity_score'
    having: RecordingFilter[]
    event?: '$rageclick' | '$exception'
    hideViewed?: boolean
}

// The web playlist's default drops sessions with 5 active seconds or fewer. "Worth watching" follows the backend
// recipe: dense sessions first, at least 10 active seconds, shorter than 30 minutes, not seen on the web yet.
const SOURCE_QUERIES: Record<FeedSource, SourceQuery> = {
    newest: { order: 'start_time', having: [{ type: 'recording', key: 'active_seconds', operator: 'gt', value: 5 }] },
    worth: {
        order: 'activity_score',
        having: [
            { type: 'recording', key: 'active_seconds', operator: 'gt', value: 10 },
            { type: 'recording', key: 'duration', operator: 'lt', value: 1800 },
        ],
        hideViewed: true,
    },
    rage: {
        order: 'start_time',
        having: [{ type: 'recording', key: 'active_seconds', operator: 'gt', value: 5 }],
        event: '$rageclick',
    },
    errors: {
        order: 'start_time',
        having: [{ type: 'recording', key: 'active_seconds', operator: 'gt', value: 5 }],
        event: '$exception',
    },
}

/** `GET session_recordings/` with the source's filters. Every value goes through the server's JSON decoding. */
export async function fetchFeedRecordings(
    source: FeedSource,
    after: string | undefined,
    signal?: AbortSignal
): Promise<RecordingsListApi> {
    const config = SOURCE_QUERIES[source]
    return apiJson<RecordingsListApi>(projectPath('session_recordings/'), {
        query: {
            limit: FEED_PAGE_SIZE,
            date_from: FEED_FROM,
            order: config.order,
            order_direction: 'DESC',
            filter_test_accounts: true,
            having_predicates: JSON.stringify(config.having),
            events: config.event
                ? JSON.stringify([{ id: config.event, type: 'events', name: config.event }])
                : undefined,
            hide_viewed_recordings: config.hideViewed ? JSON.stringify('current-user') : undefined,
            after,
        },
        signal,
    })
}

export async function fetchFeedObservations(sessionIds: readonly string[], signal?: AbortSignal) {
    return apiJson<ObservationListApi>(projectPath('vision/observations/'), {
        query: { session_id: sessionIds.join(',') },
        signal,
    })
}

export const FEED_EVENT_COLUMNS = [
    'timestamp',
    'event',
    'pathname',
    'screen_name',
    'element_texts',
    'exception_types',
    'exception_values',
    'browser',
    'os',
    'viewport_width',
    'viewport_height',
    'screen_width',
    'screen_height',
] as const

export const FEED_EVENTS_LIMIT = 500
/** Events can arrive a little before the first snapshot or after the last one. */
const WINDOW_PADDING_MS = 60_000

/**
 * Everything a card marks on its scrubber, in one query: page views, clicks, rage and dead clicks, exceptions and the
 * team's own events. The session id and the window go in as `values`, never into the query text.
 */
export function feedEventsQuery(sessionId: string, startTime: string, endTime: string): Record<string, unknown> {
    const from = new Date(new Date(startTime).getTime() - WINDOW_PADDING_MS).toISOString()
    const to = new Date(new Date(endTime).getTime() + WINDOW_PADDING_MS).toISOString()
    return {
        kind: 'HogQLQuery',
        query: [
            'SELECT timestamp, event, properties.$pathname, properties.$screen_name, elements_chain_texts,',
            'properties.$exception_types, properties.$exception_values, properties.$browser, properties.$os,',
            'properties.$viewport_width, properties.$viewport_height, properties.$screen_width, properties.$screen_height',
            'FROM events',
            'WHERE properties.$session_id = {session_id}',
            'AND timestamp >= toDateTime({date_from}) AND timestamp <= toDateTime({date_to})',
            "AND (event IN ('$pageview', '$screen', '$rageclick', '$dead_click', '$exception')",
            "OR (event = '$autocapture' AND properties.$event_type = 'click') OR NOT startsWith(event, '$'))",
            'ORDER BY timestamp ASC',
            `LIMIT ${FEED_EVENTS_LIMIT}`,
        ].join(' '),
        values: { session_id: sessionId, date_from: from, date_to: to },
    }
}

export async function fetchFeedEvents(
    sessionId: string,
    startTime: string,
    endTime: string,
    signal?: AbortSignal
): Promise<unknown[][]> {
    const response = (await runQuery(feedEventsQuery(sessionId, startTime, endTime), {
        signal,
        budgetFamily: 'replay',
    })) as { results?: unknown[][] }
    return Array.isArray(response?.results) ? response.results : []
}

export const feedKeys = {
    all: (scopeKeyParts: readonly unknown[]) => ['replayFeed', ...scopeKeyParts] as const,
}
