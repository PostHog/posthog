import {
    deltaBasisText,
    deltaText,
    insightDisplay,
    pinRangeLabel,
    snapshotFormatter,
} from '@/features/views/snapshotChart'
import { formatInsightValue } from '@/model/adapters/insightFormatting'
import { sqlCellNumber } from '@/model/adapters/sqlVisualization'
import type { InsightSnapshot, PinDisplay } from '@/model/views'

export interface WidgetSnapshot {
    version: 1
    pinId: string
    fetchedAt: number
    lastRefreshAt: string | null
    rangeLabel: string | null
    intervalLabel: string
    chartValueText: string | null
    axisLowText: string | null
    axisHighText: string | null
    valueText: string | null
    deltaPercent: number | null
    deltaText: string | null
    deltaBasis: string | null
    series: { label: string; points: { at: string; value: number | null }[]; previous: boolean }[]
    chartKind: 'line' | 'bar'
    display: 'number' | 'chart' | 'rows'
    rows: { label: string; value: string }[]
}

export function widgetSnapshot(
    pinId: string,
    snapshot: InsightSnapshot,
    mode: PinDisplay['mode']
): WidgetSnapshot | null {
    if (!snapshot.dataReadAt || snapshot.refreshFailed) {
        return null
    }
    const format = snapshotFormatter(snapshot)
    // Native home-screen widgets do not carry category labels or per-series axes in their snapshot format.
    const needsSqlRows =
        snapshot.sqlTable &&
        snapshot.allSeries.some(
            (series) =>
                series.points.some((point) => point.label !== undefined) ||
                series.axis === 'right' ||
                (series.chartKind !== undefined && series.chartKind !== snapshot.chartKind)
        )
    const display = needsSqlRows ? 'table' : insightDisplay(snapshot)
    if (display === 'web') {
        return null
    }
    const rows: WidgetSnapshot['rows'] = []
    if (snapshot.funnel) {
        rows.push(
            ...snapshot.funnel.steps
                .slice(0, 12)
                .map((step) => ({ label: step.name, value: step.count.toLocaleString('en-US') }))
        )
    } else if (snapshot.retention) {
        for (const cohort of snapshot.retention.cohorts.slice(0, 12)) {
            rows.push({
                label: cohort.date.slice(0, 10),
                value: cohort.cells.map((cell) => `${Math.round(cell.percent)}%`).join(' · '),
            })
        }
    } else if (snapshot.ranking) {
        rows.push(...snapshot.ranking.rows.slice(0, 12).map((row) => ({ label: row.label, value: format(row.value) })))
    } else if (snapshot.sqlTable && display !== 'chart' && display !== 'number') {
        const { columns } = snapshot.sqlTable
        for (const row of snapshot.sqlTable.rows.slice(0, 12)) {
            rows.push({
                label: String(row[0] ?? '–'),
                value: row
                    .slice(1)
                    .map((cell, index) => {
                        const column = columns[index + 1]
                        const numeric = column?.isNumerical ? sqlCellNumber(cell) : undefined
                        return numeric !== undefined && column?.format
                            ? formatInsightValue(numeric, { ...snapshot.format, presentation: column.format })
                            : String(cell ?? '–')
                    })
                    .join(' · '),
            })
        }
    }
    const plotted = needsSqlRows ? [] : snapshot.allSeries.slice(0, 10)
    const current = plotted.filter((series) => series.compare !== 'previous')
    const values = plotted
        .filter((series) => snapshot.chartKind !== 'bar' || series.compare !== 'previous')
        .flatMap((series) => series.points.slice(-60).map((point) => point.value))
        .filter(Number.isFinite)
    const latest =
        current.length === 1 ? current[0]?.points.slice(-60).findLast((point) => Number.isFinite(point.value)) : null
    const low = values.length ? Math.min(...values, ...(snapshot.chartKind === 'bar' ? [0] : [])) : null
    const high = values.length ? Math.max(...values, ...(snapshot.chartKind === 'bar' ? [0] : [])) : null
    return {
        chartValueText: latest ? format(latest.value) : null,
        axisLowText: low === null ? null : format(low),
        axisHighText: high === null ? null : format(high),
        version: 1,
        pinId,
        fetchedAt: snapshot.dataReadAt,
        lastRefreshAt: snapshot.lastRefreshAt,
        rangeLabel: pinRangeLabel(snapshot),
        intervalLabel: snapshot.interval,
        valueText:
            snapshot.funnel?.conversion !== null && snapshot.funnel?.conversion !== undefined
                ? `${Number(snapshot.funnel.conversion.toFixed(1))}%`
                : snapshot.value === null
                  ? display === 'number' && snapshot.sqlTable?.rows[0]?.[0] != null
                      ? String(snapshot.sqlTable.rows[0][0])
                      : null
                  : format(snapshot.value),
        deltaPercent: snapshot.delta?.unit === 'points' ? snapshot.delta.change : (snapshot.delta?.percent ?? null),
        deltaText: snapshot.delta ? deltaText(snapshot.delta, format) : null,
        deltaBasis: snapshot.delta ? deltaBasisText(snapshot.delta, snapshot.interval) : null,
        series: plotted.map((series) => ({
            label: series.label,
            points: series.points
                .slice(-60)
                .map((point) => ({ at: point.at, value: Number.isFinite(point.value) ? point.value : null })),
            previous: series.compare === 'previous',
        })),
        chartKind: snapshot.chartKind ?? 'line',
        display:
            mode === 'number' && snapshot.capabilities.number
                ? 'number'
                : rows.length > 0
                  ? 'rows'
                  : display === 'number'
                    ? 'number'
                    : 'chart',
        rows: mode === 'number' && snapshot.capabilities.number ? [] : rows.slice(0, 12),
    }
}
