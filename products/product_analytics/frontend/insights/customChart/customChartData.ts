/** What a custom chart canvas receives through `ph.onInsightData`. */
export interface CustomChartData {
    query: Record<string, unknown>
    results: unknown
    columns?: string[]
    types?: unknown[]
}

export function customChartDataFromResponse(
    query: Record<string, unknown> | null | undefined,
    response: Record<string, any> | null | undefined
): CustomChartData | null {
    if (!query || !response) {
        return null
    }
    const results = response.results ?? response.result
    if (results === undefined) {
        return null
    }
    return {
        query,
        results,
        ...(Array.isArray(response.columns) ? { columns: response.columns } : {}),
        ...(Array.isArray(response.types) ? { types: response.types } : {}),
    }
}

const SAMPLE_ITEMS = 8
const SAMPLE_POINTS = 30
const SAMPLE_CHARS = 12_000

function trimValue(value: unknown, depth: number): unknown {
    if (Array.isArray(value)) {
        const limit = depth === 0 ? SAMPLE_ITEMS : SAMPLE_POINTS
        return value.slice(0, limit).map((item) => trimValue(item, depth + 1))
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, trimValue(item, depth + 1)]))
    }
    return value
}

/**
 * A small copy of the data with the same shape, for the generation prompt and the canvas's sample.
 * It keeps the first few series or rows and the first points of each array.
 */
export function sampleCustomChartData(data: CustomChartData): CustomChartData {
    const size = (results: unknown): number => JSON.stringify({ ...data, results }).length
    let items = SAMPLE_ITEMS
    let results = trimValue(data.results, 0)
    // ponytail: halves the item count until the JSON fits; a deep single item can still exceed the cap.
    while (Array.isArray(results) && items > 1 && size(results) > SAMPLE_CHARS) {
        items = Math.floor(items / 2)
        results = results.slice(0, items)
    }
    return { ...data, results }
}
