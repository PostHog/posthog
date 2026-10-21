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
        return data.results
    }

    return data
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
