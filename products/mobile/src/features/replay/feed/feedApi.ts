import { apiJson, projectPath } from '@/api/client'
import { runQuery } from '@/api/query'
import type { RecordingsListApi } from '@/api/recordings'
import { fetchWatchFeed } from '@/api/replayVision'

import type { FeedSource } from './feedModel'

export const FEED_PAGE_SIZE = 10
const FEED_FROM = '-7d'
/**
 * Every list stops an hour back, so a busy project's first page is finished recordings and not the ones still being
 * recorded. The server parses it like `date_from` (`relative_date_parse`: `-1h` is one hour before now).
 */
const LIST_TO = '-1h'
/** Wider than the Highlights window, so every ranked recording is in the list query's range. */
const HIGHLIGHTS_RECORDINGS_FROM = '-8d'

interface RecordingFilter {
    type: 'recording'
    key: 'active_seconds' | 'duration'
    operator: 'gt' | 'lt'
    value: number
}

interface SourceQuery {
    order: 'start_time'
    having: RecordingFilter[]
    event?: '$rageclick' | '$exception'
}

// The web playlist's default drops sessions with 5 active seconds or fewer.
const SOURCE_QUERIES: Record<Exclude<FeedSource, 'highlights'>, SourceQuery> = {
    newest: {
        order: 'start_time',
        having: [{ type: 'recording', key: 'active_seconds', operator: 'gt', value: 5 }],
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
    signal?: AbortSignal,
    filterTestAccounts = false
): Promise<RecordingsListApi> {
    if (source === 'highlights') {
        return fetchHighlightRecordings(after, filterTestAccounts, signal)
    }
    const config = SOURCE_QUERIES[source]
    return apiJson<RecordingsListApi>(projectPath('session_recordings/'), {
        query: {
            limit: FEED_PAGE_SIZE,
            date_from: FEED_FROM,
            date_to: LIST_TO,
            order: config.order,
            order_direction: 'DESC',
            filter_test_accounts: filterTestAccounts ? true : undefined,
            having_predicates: JSON.stringify(config.having),
            events: config.event
                ? JSON.stringify([{ id: config.event, type: 'events', name: config.event }])
                : undefined,
            after,
        },
        signal,
    })
}

/** The cursor of a Highlights page: the ranked feed's offset and the time it ranks as of. */
function parseHighlightsCursor(after: string | undefined): { offset: number; asOf: string | null } {
    if (!after) {
        return { offset: 0, asOf: null }
    }
    const [offset, asOf] = after.split('|')
    return { offset: Number(offset) || 0, asOf: asOf || null }
}

/**
 * Highlights is Replay Vision's ranked feed. It returns observations, so the recordings of a page come from one list
 * call by session id, put back in the feed's order. A project without Replay Vision gets an empty page.
 */
async function fetchHighlightRecordings(
    after: string | undefined,
    filterTestAccounts: boolean,
    signal?: AbortSignal
): Promise<RecordingsListApi> {
    const cursor = parseHighlightsCursor(after)
    const feed = await fetchWatchFeed(signal, { limit: FEED_PAGE_SIZE, offset: cursor.offset, asOf: cursor.asOf })
    const ids = [...new Set((feed.results ?? []).map((item) => item.observation.session_id))]
    const next = feed.has_more ? `${cursor.offset + FEED_PAGE_SIZE}|${feed.as_of ?? cursor.asOf ?? ''}` : null
    if (ids.length === 0) {
        return { results: [], has_next: Boolean(next), next_cursor: next }
    }
    const rows = await apiJson<RecordingsListApi>(projectPath('session_recordings/'), {
        query: {
            limit: ids.length,
            date_from: HIGHLIGHTS_RECORDINGS_FROM,
            session_ids: JSON.stringify(ids),
            filter_test_accounts: filterTestAccounts ? true : undefined,
        },
        signal,
    })
    const byId = new Map((rows.results ?? []).map((row) => [row.id, row]))
    return {
        results: ids.flatMap((id) => {
            const row = byId.get(id)
            return row ? [row] : []
        }),
        has_next: Boolean(next),
        next_cursor: next,
    }
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

export const FEED_SIGNAL_COLUMNS = [
    'session_id',
    'timestamp',
    'event',
    'element_texts',
    'exception_types',
    'exception_values',
] as const

/** Each recording keeps at most this many signals, so one busy recording cannot fill the whole page's result. */
export const FEED_SIGNALS_PER_SESSION = 60

export interface SignalWindow {
    sessionIds: readonly string[]
    from: string
    to: string
}

/**
 * The rage clicks and errors of a page of recordings, in one query, for the Sessions list's reason lines and timeline
 * strips. The session ids and the window go in as `values`, never into the query text.
 */
export function feedSignalsQuery(window: SignalWindow): Record<string, unknown> {
    return {
        kind: 'HogQLQuery',
        query: [
            'SELECT properties.$session_id AS session_id, timestamp, event, elements_chain_texts,',
            'properties.$exception_types, properties.$exception_values',
            'FROM events',
            'WHERE properties.$session_id IN {session_ids}',
            'AND timestamp >= toDateTime({date_from}) AND timestamp <= toDateTime({date_to})',
            "AND event IN ('$rageclick', '$exception')",
            'ORDER BY timestamp ASC',
            `LIMIT ${FEED_SIGNALS_PER_SESSION} BY session_id`,
            `LIMIT ${FEED_SIGNALS_PER_SESSION * FEED_PAGE_SIZE}`,
        ].join(' '),
        values: { session_ids: [...window.sessionIds], date_from: window.from, date_to: window.to },
    }
}

export async function fetchFeedSignals(window: SignalWindow, signal?: AbortSignal): Promise<unknown[][]> {
    const response = (await runQuery(feedSignalsQuery(window), { signal, budgetFamily: 'replay' })) as {
        results?: unknown[][]
    }
    return Array.isArray(response?.results) ? response.results : []
}

export const feedKeys = {
    all: (scopeKeyParts: readonly unknown[]) => ['replayFeed', ...scopeKeyParts] as const,
}
