import { encode } from '@toon-format/toon'

const QUERY_PLACEHOLDER_PREFIX = '__QUERY_PLACEHOLDER_'
const QUERY_PLACEHOLDER_PATTERN = new RegExp(`${QUERY_PLACEHOLDER_PREFIX}\\d+__`, 'g')

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

export function formatResponse(data: any): string {
    if (typeof data === 'string') {
        return data
    }

    const placeholderMap = new Map<string, string>()
    const processed = preprocessKeys(data, placeholderMap)

    // The replacer must be a function, so that each query's JSON goes in literally. A
    // replacement string expands `$&`, `` $` `` and `$'` instead. A query that puts `$`
    // before a closing quote then splices the encoded response into itself. Anchored
    // regular expressions such as `'^/pricing$'` do this. One pass also stops the whole
    // string from being copied once per query.
    return encode(processed).replace(QUERY_PLACEHOLDER_PATTERN, (match) => placeholderMap.get(match) ?? match)
}
