import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY } from '@/tools/types'

export interface MatrixSeries {
    metric: Record<string, string>
    values: [string, number | null][]
}

// The default TOON text folds `values` into a table, which a reader of the Prometheus shape cannot parse.
export function withJsonText<T extends object>(result: T): T {
    const wrapped = { ...result }
    // Not enumerable, so a caller that asks for JSON does not get the text twice.
    Object.defineProperty(wrapped, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, {
        value: JSON.stringify(wrapped),
        enumerable: false,
    })
    return wrapped
}
