import type { ReactElement } from 'react'

// Deep imports on purpose — pulling from the `lib/hog-charts` barrel would
// drag every re-exported module into typecheck, including `TimeSeriesLineChart`
// and its `lib/dayjs` / `lib/utils` / `lib/statistics` transitive deps. The
// narrow alias surface only works if we reach into the specific files we need.
import { LineChart } from 'lib/hog-charts/charts/LineChart'
import type { Series } from 'lib/hog-charts/core/types'

import { MCP_CHART_THEME } from './McpChartTheme'
import type { TrendsResultItem } from './types'
import { formatDate, formatNumber, getSeriesLabel } from './utils'

export interface McpTrendsLineChartProps {
    results: TrendsResultItem[]
}

/**
 * MCP adapter from `TrendsResultItem[]` to hog-charts `LineChart`.
 *
 * Uses the lower-level `LineChart` rather than `TimeSeriesLineChart` so the
 * MCP IIFE bundle stays narrow. `TimeSeriesLineChart` transitively imports
 * `lib/dayjs`, `lib/utils`, and `lib/statistics` via its auto-axis formatters
 * and derived-series helpers — pulling those would balloon the alias surface
 * (and bundle) far beyond what the POC needs.
 *
 * Inlined mapper on purpose — the kea-bound transform module under
 * `frontend/src/scenes/trends/viz/trends-line-chart/trendsChartTransforms.ts`
 * transitively pulls `~/types` and `lib/statistics`.
 *
 * X-axis date formatting and y-axis numeric compaction are handled with the
 * MCP-local helpers in `./utils`. Hour / week / month insights will have
 * suboptimal X-axis ticks until a follow-up reads `query.dateRange` /
 * `query.interval` from the TrendsQuery.
 */
export function McpTrendsLineChart({ results }: McpTrendsLineChartProps): ReactElement | null {
    if (results.length === 0) {
        return null
    }

    const palette = MCP_CHART_THEME.colors
    const series: Series[] = results.map((item, index) => ({
        key: String(index),
        label: getSeriesLabel(item, index),
        data: item.data ?? [],
        color: palette[index % palette.length],
    }))

    const labels = results[0]?.days ?? results[0]?.labels ?? []

    return (
        <LineChart
            series={series}
            labels={labels}
            theme={MCP_CHART_THEME}
            config={{
                showGrid: true,
                showCrosshair: true,
                xTickFormatter: (label) => formatDate(label),
                yTickFormatter: (value) => formatNumber(value),
            }}
        />
    )
}
