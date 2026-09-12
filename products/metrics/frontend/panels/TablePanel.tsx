import { useMemo } from 'react'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { flattenSeriesRows, MetricsSeriesRow } from './metricsReduce'
import { thresholdColor } from './metricsThresholds'
import { formatMetricValue } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'

/** The label keys present across every series, unioned, so each gets its own column. */
function labelKeys(rows: MetricsSeriesRow[]): string[] {
    const keys = new Set<string>()
    for (const row of rows) {
        for (const key of Object.keys(row.labels)) {
            keys.add(key)
        }
    }
    return [...keys].sort()
}

/** Rows = series (one per label set); columns = label keys plus the chosen reducers. */
export function TablePanel({ series, display, unit, fallbackName }: MetricsPanelProps): JSX.Element {
    const reducer = resolveReducer(display)
    const reducers = useMemo(
        () => (display.legendCalcs?.length ? display.legendCalcs : [reducer]),
        [display.legendCalcs, reducer]
    )
    const rows = useMemo(() => flattenSeriesRows(series, reducers), [series, reducers])
    const keys = useMemo(() => labelKeys(rows), [rows])

    const columns: LemonTableColumns<MetricsSeriesRow> = [
        ...(keys.length > 0
            ? keys.map((key) => ({
                  title: key,
                  key: `label-${key}`,
                  render: (_: unknown, row: MetricsSeriesRow) => row.labels[key] ?? '—',
              }))
            : [
                  {
                      title: 'metric',
                      key: 'metric',
                      render: (_: unknown, row: MetricsSeriesRow) => row.metricName ?? fallbackName,
                  },
              ]),
        ...reducers.map((r) => ({
            title: r,
            key: `reducer-${r}`,
            align: 'right' as const,
            render: (_: unknown, row: MetricsSeriesRow) => {
                const value = row.values[r]
                const color = thresholdColor(value, display.thresholds, FALLBACK_COLOR)
                return value === null ? (
                    <span className="text-secondary">—</span>
                ) : (
                    <span style={{ color: `var(--${color})` }}>{formatMetricValue(value, unit)}</span>
                )
            },
        })),
    ]

    return (
        <div className="h-full w-full overflow-auto">
            <LemonTable
                columns={columns}
                dataSource={rows}
                rowKey={(row) => JSON.stringify(row.labels) + (row.metricName ?? '')}
                emptyState={<span className="text-secondary">No data</span>}
            />
        </div>
    )
}
