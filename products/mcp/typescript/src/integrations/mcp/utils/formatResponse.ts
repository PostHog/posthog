import { encode } from '@byjohann/toon'

const QUERY_PLACEHOLDER_PREFIX = '__QUERY_PLACEHOLDER_'
const placeholderMap = new Map<string, string>()

function preprocessKeys(obj: any, placeholderId = { current: 0 }): any {
    if (obj === null || obj === undefined) {
        return obj
    }

    if (Array.isArray(obj)) {
        return obj.map((item) => preprocessKeys(item, placeholderId))
    }

    if (typeof obj === 'object') {
        const processed: any = {}
        for (const [key, value] of Object.entries(obj)) {
            if (key === 'query' && value !== null && value !== undefined) {
                const placeholder = `${QUERY_PLACEHOLDER_PREFIX}${placeholderId.current++}__`
                placeholderMap.set(placeholder, JSON.stringify(value, null, 2))
                processed[key] = placeholder
            } else {
                processed[key] = preprocessKeys(value, placeholderId)
            }
        }
        return processed
    }

    return obj
}

export function formatResponse(data: any): string {
    placeholderMap.clear()
    const processed = preprocessKeys(data)
    let result = encode(processed)

    for (const [placeholder, jsonValue] of placeholderMap.entries()) {
        result = result.replace(`${placeholder}`, jsonValue)
    }

    return result
}
