export interface InsightActorsData {
    query: Record<string, unknown>
    results: {
        columns: string[]
        results: (string | number | null | string[])[][]
    }
    hasMore: boolean
    offset: number
    _posthogUrl?: string
}

export interface ActorRow {
    distinct_id: string | null
    email: string | null
    name: string | null
    event_count: number | null
    recordings: string[]
}

export function toActorRows(data: InsightActorsData): ActorRow[] {
    const { columns, results } = data.results
    return results.map((row) => {
        const obj: Record<string, unknown> = {}
        columns.forEach((col, i) => {
            obj[col] = row[i]
        })
        return {
            distinct_id: (obj.distinct_id as string) ?? null,
            email: (obj.email as string) ?? null,
            name: (obj.name as string) ?? null,
            event_count: (obj.event_count as number) ?? null,
            recordings: Array.isArray(obj.recordings) ? (obj.recordings as string[]) : [],
        }
    })
}
