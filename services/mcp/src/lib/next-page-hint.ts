interface PaginatedEnvelope {
    results: unknown[]
    next: string
    count?: number
}

const ENVELOPE_KEYS = ['results', 'next', 'count', 'previous']

// Other parameters in `next`, such as `search`, repeat arguments the agent already sent.
const PAGING_PARAMS = ['cursor', 'offset', 'limit', 'page']

function findPaginatedEnvelope(data: unknown): PaginatedEnvelope | null {
    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
        return null
    }
    const record = data as Record<string, unknown>
    if (!Array.isArray(record.results) || typeof record.next !== 'string' || !('previous' in record)) {
        return null
    }
    // Wrappers such as `withPostHogUrl` and `withAgentNote` add `_`-prefixed keys next to the envelope.
    const hasOtherKeys = Object.keys(record).some((key) => !ENVELOPE_KEYS.includes(key) && !key.startsWith('_'))
    if (hasOtherKeys) {
        return null
    }
    return record as unknown as PaginatedEnvelope
}

function pluralizeResults(count: number): string {
    return count === 1 ? '1 result' : `${count} results`
}

export function getNextPageHint(toolName: string, handlerResult: unknown): string | null {
    const envelope = findPaginatedEnvelope(handlerResult)
    if (!envelope) {
        return null
    }

    let params: URLSearchParams
    try {
        params = new URL(envelope.next).searchParams
    } catch {
        return null
    }

    const pagingValues = PAGING_PARAMS.filter((name) => params.has(name)).map((name) => `${name}=${params.get(name)}`)
    if (pagingValues.length === 0) {
        return null
    }

    const shown =
        typeof envelope.count === 'number'
            ? `Showing ${envelope.results.length} of ${pluralizeResults(envelope.count)}.`
            : `Showing ${pluralizeResults(envelope.results.length)}.`
    return `${shown} More results exist: call ${toolName} again with the same arguments and set ${pagingValues.join(' and ')} to get the next page.`
}
