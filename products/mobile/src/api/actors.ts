import { runQuery } from './query'

// Shapes follow `ActorsQuery`, `InsightActorsQuery` and `ActorsQueryResponse` in `posthog/schema.py`. The web's caller
// is `frontend/src/scenes/trends/persons-modal/personsModalLogic.ts`.

export const ACTORS_LIMIT = 20

export interface ActorsAtPointInput {
    /** The insight response's `query.source`, with the dashboard and tile layers applied, so people match the chart. */
    source: unknown
    /** The bucket start, as the trends result's `days` lists it. */
    day: string | number
    /** The index of the series in the trends query. */
    series: number
    breakdown?: string | number | null | (string | number | null)[]
    compare?: 'current' | 'previous' | null
    /** True for "Watch recordings": each row then carries the sessions that matched. */
    includeRecordings: boolean
}

export function actorsAtPointQuery(input: ActorsAtPointInput): Record<string, unknown> {
    const { source, day, series, breakdown, compare, includeRecordings } = input
    return {
        kind: 'ActorsQuery',
        source: {
            kind: 'InsightActorsQuery',
            source,
            day,
            series,
            ...(breakdown === undefined || breakdown === null ? {} : { breakdown }),
            ...(compare ? { compare } : {}),
            ...(includeRecordings ? { includeRecordings: true } : {}),
        },
        // `matched_recordings` reads the matching events, which the runner selects only with `includeRecordings`.
        select: includeRecordings ? ['actor', 'matched_recordings'] : ['actor'],
        limit: ACTORS_LIMIT,
    }
}

/** A person row: `{id, distinct_ids, properties, is_identified, created_at}`. */
export interface ActorApi {
    id?: string
    distinct_ids?: string[]
    properties?: Record<string, unknown>
    created_at?: string
}

/** One `matched_recordings` entry. */
export interface MatchedRecordingApi {
    session_id: string
    events?: { timestamp?: string; uuid?: string; window_id?: string }[]
}

export interface ActorsResponseApi {
    columns?: unknown[]
    /** Rows in `select` order: `[actor]` or `[actor, matched_recordings]`. */
    results?: unknown[][]
    hasMore?: boolean | null
}

/** `POST query/` with `blocking` and no polling. Callers run one actors query at a time. */
export async function fetchActorsAtPoint(input: ActorsAtPointInput, signal?: AbortSignal): Promise<ActorsResponseApi> {
    return (await runQuery(actorsAtPointQuery(input), {
        refresh: 'blocking',
        poll: false,
        signal,
    })) as ActorsResponseApi
}
