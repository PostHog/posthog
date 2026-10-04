import { encode } from '@toon-format/toon'

const QUERY_PLACEHOLDER_PREFIX = '__QUERY_PLACEHOLDER_'

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

function unwrapPaginatedResponse(data: unknown): unknown {
    if (
        data !== null &&
        typeof data === 'object' &&
        'results' in data &&
        Array.isArray(data.results) &&
        'next' in data &&
        'previous' in data &&
        Object.keys(data).every((key) => ['results', 'next', 'count', 'previous'].includes(key))
    ) {
        // Keep the envelope ahead of the rows, so a caller can still check completeness when the text is truncated.
        const envelope: Record<string, unknown> = {}
        if ('count' in data && typeof data.count === 'number') {
            envelope.count = data.count
        }
        if (typeof data.next === 'string' && data.next) {
            Object.assign(envelope, nextPageIndicator(data.next))
        }
        if (Object.keys(envelope).length === 0) {
            return data.results
        }
        return { ...envelope, results: data.results }
    }

    return data
}

function nextPageIndicator(next: string): Record<string, string | number> {
    let params: URLSearchParams
    try {
        params = new URL(next, 'http://localhost').searchParams
    } catch {
        return { next }
    }
    const offset = Number(params.get('offset'))
    if (params.has('offset') && Number.isInteger(offset)) {
        return { next_offset: offset }
    }
    const cursor = params.get('cursor')
    if (cursor) {
        return { next_cursor: cursor }
    }
    return { next }
}

export function formatResponse(data: any): string {
    if (typeof data === 'string') {
        return data
    }

    const placeholderMap = new Map<string, string>()
    const processed = preprocessKeys(unwrapPaginatedResponse(data), placeholderMap)
    let result = encode(processed)

    for (const [placeholder, jsonValue] of placeholderMap.entries()) {
        result = result.replace(`${placeholder}`, jsonValue)
    }

    return result
}
