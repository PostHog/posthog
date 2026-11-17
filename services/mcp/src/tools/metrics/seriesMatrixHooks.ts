import { type MatrixSeries, withJsonText } from '@/tools/series-matrix'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

interface RangeSeries {
    labels?: Record<string, string> | null
    points: { time: string; value: number | null }[]
    metric_name?: string | null
    clause?: string | null
}

function isRangeSeries(series: unknown): series is RangeSeries {
    return typeof series === 'object' && series !== null && Array.isArray((series as RangeSeries).points)
}

function toMatrixSeries(series: RangeSeries): MatrixSeries {
    const name = series.metric_name ?? series.clause
    return {
        metric: { ...(name ? { __name__: name } : {}), ...series.labels },
        values: series.points.map((point) => [point.time, point.value]),
    }
}

// An instant or summary response has no points to plot, so it keeps its own shape.
function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    const response = result as { results?: unknown }
    if (!Array.isArray(response?.results) || !response.results.every(isRangeSeries)) {
        return result
    }
    return withJsonText({ ...response, results: response.results.map(toMatrixSeries) })
}

export default { afterResponse } satisfies ToolHooks<unknown>
