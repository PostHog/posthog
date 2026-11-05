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
    const display = insightDisplay(snapshot)
    if (display === 'web') {
        return null
    }
    const rows: WidgetSnapshot['rows'] = []
    if (snapshot.funnel) {
        rows.push(
            ...snapshot.funnel.steps.map((step) => ({ label: step.name, value: step.count.toLocaleString('en-US') }))
        )
    } else if (snapshot.retention) {
        for (const cohort of snapshot.retention.cohorts) {
            rows.push({
                label: cohort.date.slice(0, 10),
                value: cohort.cells.map((cell) => `${Math.round(cell.percent)}%`).join(' · '),
            })
        }
    } else if (snapshot.ranking) {
        rows.push(...snapshot.ranking.rows.map((row) => ({ label: row.label, value: format(row.value) })))
    } else if (snapshot.sqlTable && display !== 'chart' && display !== 'number') {
        const { columns } = snapshot.sqlTable
        for (const row of snapshot.sqlTable.rows) {
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
    return {
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
        series: snapshot.allSeries.slice(0, 10).map((series) => ({
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
