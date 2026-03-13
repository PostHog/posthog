export function getApiErrorDetail(error: unknown): string | undefined {
    if (error !== null && typeof error === 'object') {
        if ('detail' in error && typeof error.detail === 'string') {
            return error.detail
        }

        if ('data' in error && error.data && typeof error.data === 'object') {
            for (const value of Object.values(error.data as Record<string, unknown>)) {
                if (Array.isArray(value) && typeof value[0] === 'string') {
                    return value[0]
                }

                if (typeof value === 'string') {
                    return value
                }
            }
        }
    }

    return undefined
}

export function parseTraceIdsInput(value: string): string[] {
    const dedupedTraceIds = new Set<string>()

    for (const traceId of value
        .split(/[\s,]+/)
        .map((part) => part.trim())
        .filter(Boolean)) {
        dedupedTraceIds.add(traceId)
    }

    return [...dedupedTraceIds]
}

export function formatTraceIdsInput(traceIds: string[]): string {
    return traceIds.join('\n')
}
