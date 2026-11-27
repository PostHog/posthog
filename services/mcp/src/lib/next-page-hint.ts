interface PaginatedEnvelope {
    results: unknown[]
    next: string
    count?: unknown
    count_is_capped?: unknown
}

// Other parameters in `next`, such as `search`, repeat arguments the agent already sent.
const PAGING_PARAMS = ['cursor', 'offset', 'limit', 'page']

function findPaginatedEnvelope(data: unknown): PaginatedEnvelope | null {
    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
        return null
    }
    const record = data as Record<string, unknown>
    // Unlike `unwrapPaginatedResponse` in response.ts, accept keys next to the envelope, such as `_posthogUrl` or the
    // inbox list's `ranker`: unwrapping would drop them, but this hint only adds a footer.
    if (
        !Array.isArray(record.results) ||
        typeof record.next !== 'string' ||
        !(typeof record.previous === 'string' || record.previous === null)
    ) {
        return null
    }
    return record as unknown as PaginatedEnvelope
}

function pluralizeResults(count: number): string {
    return count === 1 ? '1 result' : `${count} results`
}

function describeShownResults(envelope: PaginatedEnvelope): string {
    const shown = envelope.results.length
    if (typeof envelope.count !== 'number') {
        return `Showing ${pluralizeResults(shown)}.`
    }
    const total =
        envelope.count_is_capped === true ? `at least ${envelope.count} results` : pluralizeResults(envelope.count)
    return `Showing ${shown} of ${total}.`
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

    return `${describeShownResults(envelope)} More results exist: call ${toolName} again with the same arguments and set ${pagingValues.join(' and ')} to get the next page.`
}
