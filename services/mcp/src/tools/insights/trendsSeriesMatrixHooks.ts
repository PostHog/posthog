import { type MatrixSeries } from '@/tools/series-matrix'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

interface TrendSeries {
    label?: string | null
    days: string[]
    data: (number | null)[]
    action?: { custom_name?: string | null; name?: string | null } | null
    breakdown_value?: unknown
    compare_label?: string | null
}

function isTrendSeries(series: unknown): series is TrendSeries {
    const candidate = series as TrendSeries | null
    return (
        typeof candidate === 'object' &&
        candidate !== null &&
        Array.isArray(candidate.days) &&
        Array.isArray(candidate.data) &&
        candidate.days.length === candidate.data.length
    )
}

function toMatrixSeries(series: TrendSeries): MatrixSeries {
    const name = series.action?.custom_name ?? series.action?.name ?? series.label
    const breakdown = series.breakdown_value
    return {
        metric: {
            ...(name ? { series: name } : {}),
            ...(breakdown !== undefined && breakdown !== null
                ? { breakdown: Array.isArray(breakdown) ? breakdown.join(', ') : String(breakdown) }
                : {}),
            ...(series.compare_label ? { compare: series.compare_label } : {}),
        },
        values: series.days.map((day, index) => [day, series.data[index] ?? null]),
    }
}

// A total-value display such as a number or a pie has one value per series and no dates, so it keeps its own shape.
function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    const response = result as { results?: unknown }
    if (!Array.isArray(response?.results) || !response.results.every(isTrendSeries)) {
        return result
    }
    return { ...response, results: response.results.map(toMatrixSeries) }
}

export default { afterResponse } satisfies ToolHooks<unknown>
