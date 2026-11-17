import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY } from '@/tools/types'

/** One series in the shape of a Prometheus range result: its labels, then `[time, value]` pairs. */
export interface MatrixSeries {
    metric: Record<string, string>
    values: [string, number | null][]
}

/**
 * Sets JSON as the text of a result. The default TOON text folds `values` into a table,
 * and a client that reads the Prometheus shape then no longer finds it.
 */
export function withJsonText<T extends object>(result: T): T {
    const wrapped = { ...result }
    // Not enumerable, so a caller that asks for JSON does not get the text twice.
    Object.defineProperty(wrapped, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, {
        value: JSON.stringify(wrapped),
        enumerable: false,
    })
    return wrapped
}
