export interface InsightApiResponse {
    results: unknown
    formatted_results?: string
}

export interface ActorsApiResponse {
    results: unknown
    columns?: unknown
    hasMore?: boolean
    offset?: number
}

export type QueryResponse = InsightApiResponse | ActorsApiResponse

/**
 * A strategy pairs a request transformer with a response formatter.
 * Each strategy reads only the response fields it cares about
 */
export interface QueryStrategy {
    formatRequest(query: Record<string, unknown>): Record<string, unknown>
    formatResponse(
        response: QueryResponse,
        query: Record<string, unknown>,
        baseUrl: string,
        urlPrefix: string | undefined
    ): Record<string, unknown>
}

// Insight strategy
const insightStrategy: QueryStrategy = {
    formatRequest: (query) => query,
    formatResponse: (response, query, baseUrl, urlPrefix) => {
        const result = response as InsightApiResponse
        return {
            results: result.formatted_results ?? result.results,
            _posthogUrl: buildInsightUrl(baseUrl, urlPrefix, query),
        }
    },
}

function buildInsightUrl(baseUrl: string, urlPrefix: string | undefined, query: Record<string, unknown>): string {
    if (urlPrefix) {
        return `${baseUrl}${urlPrefix}`
    }
    const q = encodeURIComponent(JSON.stringify({ kind: 'InsightVizNode', source: query }))
    return `${baseUrl}/insights/new#q=${q}`
}

// Actors strategies
const ACTORS_DEFAULT_LIMIT = 100
const ACTORS_RESPONSE_COLUMNS = ['distinct_id', 'email', 'name', 'event_count']

function deriveActorName(props: Record<string, unknown>, fallback: string | null): string | null {
    if (typeof props.name === 'string' && props.name) {
        return props.name
    }
    if (typeof props.first_name === 'string' && props.first_name) {
        return props.first_name
    }
    return fallback
}

function projectActorRow(tuple: unknown): (string | number | null)[] {
    const row = Array.isArray(tuple) ? tuple : [tuple]
    const actor = (row[0] ?? {}) as { distinct_ids?: string[]; properties?: Record<string, unknown> }
    const props = actor.properties ?? {}
    const distinctId = actor.distinct_ids?.[0] ?? null
    const email = typeof props.email === 'string' ? props.email : null
    const name = deriveActorName(props, email ?? distinctId)
    const eventCount = typeof row[1] === 'number' ? row[1] : null
    return [distinctId, email, name, eventCount]
}

const baseActorsStrategy: QueryStrategy = {
    formatRequest: (query) => ({
        kind: 'ActorsQuery',
        source: query,
        select: ['actor', 'event_count'],
        orderBy: ['event_count DESC, actor_id DESC'],
        limit: ACTORS_DEFAULT_LIMIT,
    }),
    formatResponse: (response, query) => {
        const result = response as ActorsApiResponse
        const rows = Array.isArray(result.results) ? result.results : []
        return {
            query,
            results: {
                columns: ACTORS_RESPONSE_COLUMNS,
                results: rows.map(projectActorRow),
            },
            hasMore: result.hasMore ?? false,
            offset: result.offset ?? 0,
        }
    },
}

// Per-kind strategy overrides. Add entries here as new actors kinds land. Each kind
// can override any subset of QueryStrategy; missing fields fall back to baseActorsStrategy.
const strategiesByKind: Record<string, QueryStrategy> = {
    InsightActorsQuery: baseActorsStrategy,
}

export function resolveStrategy(kind: string): QueryStrategy {
    return strategiesByKind[kind] ?? insightStrategy
}
