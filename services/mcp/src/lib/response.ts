import { encode } from '@toon-format/toon'

const QUERY_PLACEHOLDER_PREFIX = '__QUERY_PLACEHOLDER_'
const QUERY_PLACEHOLDER_PATTERN = /__QUERY_PLACEHOLDER_\d+__/g

function preprocessKeys(obj: any, placeholderMap: Map<string, string>, placeholderId = { current: 0 }): any {
    if (obj === null || obj === undefined) {
        return obj
    }

    if (Array.isArray(obj)) {
        return obj.map((item) => preprocessKeys(item, placeholderMap, placeholderId))
    }

    if (typeof obj === 'object') {
        const processed: any = {}
        for (const [key, value] of Object.entries(obj)) {
            if (key === 'query' && value !== null && value !== undefined) {
                const placeholder = `${QUERY_PLACEHOLDER_PREFIX}${placeholderId.current++}__`
                placeholderMap.set(placeholder, JSON.stringify(value, null, 2))
                processed[key] = placeholder
            } else {
                processed[key] = preprocessKeys(value, placeholderMap, placeholderId)
            }
        }
        return processed
    }

    return obj
}

interface PaginatedEnvelope {
    results: unknown[]
    next: string | null
    previous: string | null
    count?: number
}

function isPaginatedEnvelope(data: unknown): data is PaginatedEnvelope {
    return (
        data !== null &&
        typeof data === 'object' &&
        'results' in data &&
        Array.isArray(data.results) &&
        'next' in data &&
        'previous' in data &&
        Object.keys(data).every((key) => ['results', 'next', 'count', 'previous'].includes(key))
    )
}

// The text output drops the envelope, so this line is the only way an agent learns that another page exists.
const NEXT_PAGE_PARAMS = ['cursor', 'offset', 'limit', 'page'] as const

function describeNextPage(envelope: PaginatedEnvelope): string | null {
    if (!envelope.next) {
        return null
    }

    let params: URLSearchParams
    try {
        params = new URL(envelope.next).searchParams
    } catch {
        return null
    }

    const nextPageParams = NEXT_PAGE_PARAMS.filter((name) => params.has(name)).map(
        (name) => `${name}=${params.get(name)}`
    )
    if (nextPageParams.length === 0) {
        return null
    }

    const shown =
        typeof envelope.count === 'number'
            ? `Showing ${envelope.results.length} of ${envelope.count} results.`
            : `Showing ${envelope.results.length} results.`
    return `${shown} More results exist: call the tool again with ${nextPageParams.join(' and ')} to get the next page.`
}

export function formatResponse(data: any): string {
    if (typeof data === 'string') {
        return data
    }

    const envelope = isPaginatedEnvelope(data) ? data : null
    const placeholderMap = new Map<string, string>()
    const processed = preprocessKeys(envelope ? envelope.results : data, placeholderMap)
    const result = encode(processed)

    // Use a replacer function so `$&`, `$'` and similar sequences in query JSON stay literal.
    // One pass means inserted JSON never becomes a target for a later placeholder.
    const text = result.replace(
        QUERY_PLACEHOLDER_PATTERN,
        (placeholder) => placeholderMap.get(placeholder) ?? placeholder
    )
    const nextPage = envelope ? describeNextPage(envelope) : null
    return nextPage ? `${text}\n\n${nextPage}` : text
}
